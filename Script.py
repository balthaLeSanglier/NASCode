import json
import ipaddress
import os
import sys
import uuid

def load_intent_file(file_path):
    with open(file_path, 'r') as f:
        return json.load(f)

def calculate_ips(network_intent):
    network = network_intent["network"]
    
    base_loopback = ipaddress.ip_network(network["loopbacks"]["base"].replace(" 255.255.255.255", "/32"))
    increment = network["loopbacks"]["increment"]
    
    subnets = {}
    for name, subnet in network["subnets"].items():
        subnets[name] = ipaddress.ip_network(subnet.replace(" 255.255.255.252", "/30"))
    
    for i, (router_name, router_data) in enumerate(network["routers"].items()):
        if router_data["type"] in ["PE", "P"]:
            loopback_ip = str(base_loopback.network_address + (i + 1))
        else:
            loopback_ip = f"10.0.0.{router_data['asn']}"
        
        router_data["loopback"] = f"{loopback_ip} 255.255.255.255"
        
        for intf, intf_data in router_data["interfaces"].items():
            subnet = subnets[intf_data["subnet"]]
            host_ip = subnet.network_address + intf_data["host_position"]
            intf_data["ip"] = f"{host_ip} 255.255.255.252"
    
    for router_name, router_data in network["routers"].items():
        if router_data["type"] == "CE":
            for intf, intf_data in router_data["interfaces"].items():
                subnet = subnets[intf_data["subnet"]]
                host_ip = subnet.network_address + intf_data["host_position"]
                intf_data["ip"] = f"{host_ip} 255.255.255.252"
    
    return network_intent

def generate_pe_config(router_name, router_data, asn, network):
    config = "!\n"
    config += f"hostname {router_name}\n!\nboot-start-marker\nboot-end-marker\n!\n"
    config += "no aaa new-model\nno ip icmp rate-limit unreachable\nip cef\n!\n"
    
    # Configuration VRF avec RD et Route-Targets cohérents
    if router_data["type"] == "PE":
        for customer in router_data["vrfs"]:
            customer_id = customer.split("_")[1]
            config += f"ip vrf {customer}\n"
            config += f" rd 1:{customer_id}\n"  # RD format fixe
            config += f" route-target export {asn}:{customer_id}\n"
            config += f" route-target import {asn}:{customer_id}\n!\n"
    
    loopback_ip = router_data['loopback']
    config += f"interface Loopback0\n ip address {loopback_ip}\n!\n"
    
    for intf_name in sorted(router_data["interfaces"].keys()):
        intf_data = router_data["interfaces"][intf_name]
        config += f"interface {intf_name}\n"
        
        if 'vrf' in intf_data:
            config += f" ip vrf forwarding {intf_data['vrf']}\n"
        
        config += f" ip address {intf_data['ip']}\n"
        
        if intf_data.get('mpls', False):
            config += " mpls ip\n"
        
        config += " no shutdown\n!\n"
    
    # OSPF avec tous les réseaux nécessaires
    config += "router ospf 1\n"
    if router_data["type"] in ["PE", "P"]:
        config += f" router-id {loopback_ip.split()[0]}\n"
        config += f" network {loopback_ip.split()[0]} 0.0.0.0 area 0\n"
        
        for intf, intf_data in router_data["interfaces"].items():
            if "neighbor" in intf_data:
                subnet_key = intf_data["subnet"]
                subnet = network["subnets"][subnet_key].split()[0]
                config += f" network {subnet} 0.0.0.3 area 0\n"
    
    config += "mpls ldp router-id Loopback0 force\n!\n"
    
    # Configuration BGP complète pour PE et P
    config += f"router bgp {asn}\n"
    config += f" bgp router-id {loopback_ip.split()[0]}\n"
    config += " bgp log-neighbor-changes\n"
    config += " no bgp default ipv4-unicast\n"
    
    # Sessions avec tous les PE/P
    for peer_name, peer_data in network["routers"].items():
        if peer_data["type"] in ["PE", "P"] and peer_name != router_name:
            peer_loopback = peer_data["loopback"].split()[0]
            config += f" neighbor {peer_loopback} remote-as {asn}\n"
            config += f" neighbor {peer_loopback} update-source Loopback0\n"
    
    config += "!\n address-family vpnv4\n"
    for peer_name, peer_data in network["routers"].items():
        if peer_data["type"] in ["PE", "P"] and peer_name != router_name:
            peer_loopback = peer_data["loopback"].split()[0]
            config += f"  neighbor {peer_loopback} activate\n"
            config += f"  neighbor {peer_loopback} send-community both\n"
    config += " exit-address-family\n"
    
    # Configuration VRF avec route-maps explicites
    if router_data["type"] == "PE":
        for vrf in router_data["vrfs"]:
            customer_id = vrf.split("_")[1]
            for intf, intf_data in router_data["interfaces"].items():
                if "vrf" in intf_data and intf_data["vrf"] == vrf:
                    ce_ip = intf_data["ip"].split()[0]
                    ce_position = 3 - intf_data["host_position"]
                    ce_ip_obj = ipaddress.IPv4Address(ce_ip)
                    ce_neighbor_ip = str(ce_ip_obj + (1 if ce_position == 2 else -1))
                    
                    config += f"!\n address-family ipv4 vrf {vrf}\n"
                    config += "  redistribute connected\n"
                    config += f"  neighbor {ce_neighbor_ip} remote-as {intf_data['ce_asn']}\n"
                    config += f"  neighbor {ce_neighbor_ip} activate\n"
                    config += f"  neighbor {ce_neighbor_ip} route-map RM_TAG_FROM_{vrf} in\n"
                    config += f"  neighbor {ce_neighbor_ip} route-map RM_FILTER_TO_{vrf} out\n"
                    config += f" exit-address-family\n"
    
    # Définition des route-maps et communautés
    if router_data["type"] == "PE":
        for vrf in router_data["vrfs"]:
            customer_id = vrf.split("_")[1]
            config += f"!\nip community-list {customer_id} permit {asn}:{customer_id}00\n"
            config += f"route-map RM_TAG_FROM_{vrf} permit 10\n"
            config += f" set community {asn}:{customer_id}00\n!\n"
            config += f"route-map RM_FILTER_TO_{vrf} permit 10\n"
            config += f" match community {customer_id}\n!\n"
    
    config += "!\nip forward-protocol nd\n!\nno ip http server\nno ip http secure-server\n!\n"
    config += "control-plane\n!\nline con 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\n!\n"
    config += "line aux 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\n!\n"
    config += "line vty 0 4\n login\n!\nend\n"
    
    return config

def generate_ce_config(router_name, router_data, asn, pe_connection):
    config = "!\n"
    config += f"hostname {router_name}\n!\nboot-start-marker\nboot-end-marker\n!\n"
    config += "no aaa new-model\nno ip icmp rate-limit unreachable\nip cef\n!\n"
    config += "no ip domain lookup\nno ipv6 cef\n!\n"
    
    loopback_ip = router_data['loopback']
    config += f"interface Loopback0\n ip address {loopback_ip}\n!\n"
    
    for intf_name in sorted(router_data["interfaces"].keys()):
        intf_data = router_data["interfaces"][intf_name]
        config += f"interface {intf_name}\n"
        config += f" ip address {intf_data['ip']}\n"
        config += " no shutdown\n!\n"
    
    config += f"router bgp {asn}\n"
    config += " bgp log-neighbor-changes\n"
    config += f" neighbor {pe_connection['pe_ip']} remote-as {pe_connection['pe_asn']}\n"
    config += " !\n address-family ipv4\n"
    config += f"  network {loopback_ip.split()[0]} mask 255.255.255.255\n"
    subnet = ipaddress.ip_network(f"{pe_connection['interface_ip']}/30", strict=False)
    config += f"  network {subnet.network_address} mask 255.255.255.252\n"
    config += f"  neighbor {pe_connection['pe_ip']} activate\n"
    config += " exit-address-family\n!\n"
    
    config += "!\ncontrol-plane\n!\nline con 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\n!\n"
    config += "line aux 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\n!\n"
    config += "line vty 0 4\n login\n!\nend\n"
    
    return config

def generate_router_mapping(network):
    return {
        router_name: {
            "idRouter": str(uuid.uuid4()),
            "id": f"i{index+1}"
        }
        for index, router_name in enumerate(network["routers"].keys())
    }

def generate_configurations(network_intent):
    configurations = {}
    network = network_intent["network"]
    
    dicoCorrespondance = generate_router_mapping(network)
    
    for router_name, router_data in network["routers"].items():
        if router_data["type"] in ["PE", "P"]:
            config = generate_pe_config(router_name, router_data, network["asn"], network)
            configurations[router_name] = config
    
    for router_name, router_data in network["routers"].items():
        if router_data["type"] == "CE":
            pe_connection = None
            for intf, intf_data in router_data["interfaces"].items():
                if intf_data.get("connected_to_pe", False):
                    pe_name = next(
                        (name for name, data in network["routers"].items() 
                         if data["type"] == "PE" and 
                         any(i["subnet"] == intf_data["subnet"] for i in data["interfaces"].values())),
                        None
                    )
                    if pe_name:
                        pe_asn = network["asn"]
                        pe_ip = next(
                            i["ip"].split()[0] for i in network["routers"][pe_name]["interfaces"].values()
                            if i["subnet"] == intf_data["subnet"]
                        )
                        pe_connection = {
                            "interface": intf,
                            "interface_ip": intf_data["ip"].split()[0],
                            "pe_ip": pe_ip,
                            "pe_asn": pe_asn
                        }
                        break
            
            if pe_connection:
                config = generate_ce_config(router_name, router_data, router_data["asn"], pe_connection)
                configurations[router_name] = config
    
    return configurations, dicoCorrespondance

def save_configurations(configurations, dicoCorrespondance, path):
    for router_name, config in configurations.items():
        full_dir = os.path.join(path, dicoCorrespondance[router_name]["idRouter"], "configs")
        print(full_dir)
        os.makedirs(full_dir, exist_ok=True)
        output_path = os.path.join(full_dir, f"{dicoCorrespondance[router_name]['id']}_startup-config.cfg")
        with open(output_path, "w", encoding='utf-8') as f:
            f.write(config)

def main(path):
    intent = load_intent_file("intent.json")
    intent = calculate_ips(intent)
    configs, mapping = generate_configurations(intent)
    save_configurations(configs, mapping, path)
    print("\nGénération des configurations terminée!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py ./Configs")
        sys.exit(1)
    main(sys.argv[1])