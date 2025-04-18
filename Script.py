import json
import ipaddress
import os
import sys

def load_intent_file(file_path):
    """Charge le fichier JSON d'intention"""
    with open(file_path, 'r') as f:
        return json.load(f)

def calculate_ips(network_intent):
    """Calcule toutes les adresses IP"""
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
    
    return network_intent

def generate_pe_config(router_name, router_data, asn, peers, ces, network):
    """GÃ©nÃ¨re la configuration pour un routeur PE ou P"""
    config = "!\n"
    # if router_name != "PE1":
    #     config += "! Last configuration change at 17:22:40 UTC Wed Apr 2 2025\n"
    # config += "!version 15.2\n" if router_name in ["P2", "P3"] else "version 15.2\n"
    # config += "service timestamps debug datetime msec\n"
    # config += "service timestamps log datetime msec\n!\n"
    config += f"hostname {router_name}\n!\nboot-start-marker\nboot-end-marker\n!\n"
    config += "no aaa new-model\nno ip icmp rate-limit unreachable\nip cef\n!\n"
    
    # VRFs pour les PE
    if router_data["type"] == "PE":
        for customer in router_data["vrfs"]:
            config+= "ip vrf "+customer+"\n rd 1:"+customer.split("_")[1] + "\n route-target export 1:"+customer.split("_")[1]+"\n route-target import 1:"+customer.split("_")[1]+"\n!\n"

    # config += "!\n!\n" if router_name == "PE1" else ""
    # config += "no ip domain lookup\nno ipv6 cef\n!\n"
    # config += "multilink bundle-name authenticated\n!\n"
    # config += "!\n!\n!\n!\n!\n!\n!\n!\n" if router_name == "PE1" else ""
    # config += "ip tcp synwait-time 5\n!\n"
    # if router_name == "PE1":
    #     config += "!\n!\n!\n!\n!\n!\n!\n!\n!\n!\n!\n"
    
    # Interfaces
    loopback_ip = router_data['loopback']
    config += f"interface Loopback0\n ip address {loopback_ip}\n!\n"
    
    interface_count = 6
    for i in range(interface_count + 1):
        intf_name = f"FastEthernet0/0" if i == 0 else f"GigabitEthernet{i}/0"
        intf_config = router_data["interfaces"].get(intf_name)
        
        config += f"interface {intf_name}\n"
        if intf_config:
            if 'vrf' in intf_config:
                config += f" ip vrf forwarding {intf_config['vrf']}\n"
            config += f" ip address {intf_config['ip']}\n"
            if intf_config.get('mpls', False):
                config += " mpls ip\n"
            config += " negotiation auto\n"
            # if (router_name == "P2" and intf_name in ["GigabitEthernet1/0", "GigabitEthernet2/0"]) or \
            #    (router_name == "P3" and intf_name in ["GigabitEthernet2/0", "GigabitEthernet3/0"]) or \
            #    (router_name == "PE2" and intf_name == "GigabitEthernet3/0"):
            config += " no shutdown\n"

        else:
            if intf_name.startswith("FastEthernet"):
                config += " no ip address\n shutdown\n duplex full\n"
            else:
                config += " no ip address\n shutdown\n negotiation auto\n"
        config += "!\n"
    
    # OSPF
    config += "router ospf 1\n"
    if router_data["type"] in ["PE", "P"]:
        config+=" router-id "+dicoCorrespondance[router_name]["id"].strip('i')+"."+dicoCorrespondance[router_name]["id"].strip('i')+"."+dicoCorrespondance[router_name]["id"].strip('i')+"."+dicoCorrespondance[router_name]["id"].strip('i')+"\n"
        config += f" network {loopback_ip.split()[0]} 0.0.0.0 area 0\n"
        for iface, data in router_data["interfaces"].items():
            if "neighbor" in data:
                subnet_name = f"{router_name}-{data['neighbor']}"
                if subnet_name not in network["subnets"]:
                    subnet_name = f"{data['neighbor']}-{router_name}"

                subnet = network["subnets"][subnet_name]
                config += " network "+subnet.split()[0] +" 0.0.0.3 area 0\n"
            # network 192.168.69.0 0.0.0.3 area 0
        # config += " network "192.168.69.0 0.0.0.3 area 0\n"
    # if router_name == "PE1":
    #     config += " router-id 1.1.1.1\n"
    # elif router_name == "PE2":
    #     config += " router-id 4.4.4.4\n"
    # else:
    #     config += f" router-id {loopback_ip.split()[0]}\n"
    # config += f" network {loopback_ip.split()[0]} 0.0.0.0 area 0\n"
    # if router_name == "PE1":
    #     config += " network 192.168.69.0 0.0.0.3 area 0\n"
    # elif router_name == "PE2":
    #     config += " network 192.168.69.8 0.0.0.3 area 0\n"
    # elif router_name == "P2":
    #     config += " network 192.168.69.0 0.0.0.3 area 0\n network 192.168.69.4 0.0.0.3 area 0\n"
    # elif router_name == "P3":
    #     config += " network 192.168.69.4 0.0.0.3 area 0\n network 192.168.69.8 0.0.0.3 area 0\n"
    # config += "!\n"
    
    # MPLS
    config += "mpls ldp router-id Loopback0 force\n!\n"
    
    # BGP
    config += f"router bgp {asn}\n"
    config += f" bgp router-id {loopback_ip.split()[0]}\n bgp log-neighbor-changes\n"
    config += " no bgp default ipv4-unicast\n"
    
    if router_data["type"] in ["PE"]:
        for name, router in network["routers"].items():
            if router["type"] == "PE" and name != router_name:
                config+=" neighbor "+router["loopback"].split()[0] + " remote-as 2025\n neighbor "+router["loopback"].split()[0] + " update-source Loopback0\n"
    
    config += " !\n address-family ipv4\n"
    config += " exit-address-family\n"    
    config += " !\n address-family vpnv4\n"
    if router_data["type"] in ["PE"]:
        for name, router in network["routers"].items():
            if router["type"] == "PE" and name != router_name:
                config+="  neighbor "+router["loopback"].split()[0] + " activate\n "+" neighbor "+router["loopback"].split()[0] + " send-community both\n"

    if router_data["type"] in ["PE"]:
        for customer in router_data["vrfs"]:
            config += " !\n address-family vpnv4 "+customer
            config+= "\n  neighbor 192.168.70.2 remote-as "+str(asn)
            customerIp="" 
    # if router_data["type"] in ["PE"]:
    #     for customer in router_data["vrfs"]:
            
    #     for name, router in network["routers"].items():
    #         if router["type"] == "PE" and name != router_name:
    #             config+=" neighbor "+router["loopback"].split()[0] + " remote-as 2025\n neighbor "+router["loopback"].split()[0] + " update-source Loopback0\n"

    # if router_data["type"] == "PE":
    #     if router_name == "PE1":
    #         config += " !\n address-family vpnv4\n  neighbor 10.0.0.4 activate\n  neighbor 10.0.0.4 send-community both\n exit-address-family\n"
    #         config += " !\n address-family ipv4 vrf customer_1\n  redistribute connected\n  neighbor 192.168.70.2 remote-as 101\n  neighbor 192.168.70.2 activate\n  neighbor 192.168.70.2 route-map TAG_FROM_CE1-1 in\n exit-address-family\n"
    #         config += " !\n address-family ipv4 vrf customer_2\n  redistribute connected\n  neighbor 192.168.71.2 remote-as 102\n  neighbor 192.168.71.2 activate\n  neighbor 192.168.71.2 route-map TAG_FROM_CE2-1 in\n exit-address-family\n"
    #     elif router_name == "PE2":
    #         config += " !\n address-family vpnv4\n  neighbor 10.0.0.1 activate\n  neighbor 10.0.0.1 send-community both\n exit-address-family\n"
    #         config += " !\n address-family ipv4 vrf customer_1\n  redistribute connected\n  neighbor 192.168.72.2 remote-as 103\n  neighbor 192.168.72.2 activate\n  neighbor 192.168.72.2 route-map TAG_FROM_CE1-2 in\n  neighbor 192.168.72.2 route-map FILTER_TO_CE1-2 out\n exit-address-family\n"
    #         config += " !\n address-family ipv4 vrf customer_2\n  redistribute connected\n  neighbor 192.168.73.2 remote-as 104\n  neighbor 192.168.73.2 activate\n  neighbor 192.168.73.2 route-map TAG_FROM_CE2-2 in\n exit-address-family\n"
    
    config += "!\nip forward-protocol nd\n!\nno ip http server\nno ip http secure-server\n!\n"
    if router_name == "PE1":
        config += "!\n"
    config += "control-plane\n!\nline con 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\n!\n"
    config += "line aux 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\n!\n"
    config += "line vty 0 4\n login\n!\n"
    
    # Ajout des route-maps et community-lists pour PE1 et PE2
    if router_name == "PE1":
        config += "!\nroute-map TAG_FROM_CE1-1 permit 10\n set community 2025:100\n!\n"
        config += "route-map TAG_FROM_CE2-1 permit 10\n set community 2025:200\n!\n"
    elif router_name == "PE2":
        config += "!\nip community-list 1 permit 2025:100\n!\n"
        config += "route-map TAG_FROM_CE1-2 permit 10\n set community 2025:100\n!\n"
        config += "route-map TAG_FROM_CE2-2 permit 10\n set community 2025:200\n!\n"
        config += "route-map FILTER_TO_CE1-2 permit 10\n match community 1\n!\n"
        config += "route-map FILTER_TO_CE1-2 deny 20\n!\n"
    
    config += "end\n"
    
    # Ajustement des timestamps pour PE2
    if router_name == "PE2":
        config = config.replace("! Last configuration change at 17:22:40 UTC Wed Apr 2 2025", "! Last configuration change at 17:49:52 UTC Wed Apr 2 2025")
    return config

def generate_ce_config(router_name, router_data, asn, pe_connection):
    """GÃ©nÃ¨re la configuration pour un routeur CE"""
    config = "!\n"
    if router_name == "CE1-1":
        config += "! Last configuration change at 17:22:40 UTC Wed Apr 2 2025\n!"
    elif router_name == "CE2-1":
        config += "! Last configuration change at 17:30:18 UTC Wed Apr 2 2025\n!"
    elif router_name == "CE1-2":
        config += "! Last configuration change at 17:45:57 UTC Wed Apr 2 2025\n!"
    elif router_name == "CE2-2":
        config += "! Last configuration change at 17:48:33 UTC Wed Apr 2 2025\n!"
    
    config += "version 15.2\nservice timestamps debug datetime msec\n"
    config += "service timestamps log datetime msec\n!\n"
    config += f"hostname {router_name}\n!\nboot-start-marker\nboot-end-marker\n!\n"
    config += "no aaa new-model\nno ip icmp rate-limit unreachable\nip cef\n!\n"
    config += "!\n!\n!\n!\n!\n" if router_name != "CE1-1" else ""
    config += "no ip domain lookup\nno ipv6 cef\n!\n"
    config += "multilink bundle-name authenticated\n!\n"
    config += "!\n!\n!\n!\n!\n!\n!\n!\n" if router_name == "CE1-1" else ""
    config += "ip tcp synwait-time 5\n!\n!\n!\n!\n!\n!\n!\n!\n!\n!\n!\n!\n"
    
    loopback_ip = router_data['loopback']
    config += f"interface Loopback0\n ip address {loopback_ip}\n!\n"
    
    interface_count = 6
    for i in range(interface_count + 1):
        intf_name = f"FastEthernet0/0" if i == 0 else f"GigabitEthernet{i}/0"
        intf_config = router_data["interfaces"].get(intf_name)
        
        config += f"interface {intf_name}\n"
        if intf_config:
            config += f" ip address {intf_config['ip']}\n negotiation auto\n"
        else:
            if intf_name.startswith("FastEthernet"):
                config += " no ip address\n shutdown\n duplex full\n"
            else:
                config += " no ip address\n shutdown\n negotiation auto\n"
        config += "!\n"
    
    config += f"router bgp {asn}\n bgp log-neighbor-changes\n"
    config += f" neighbor {pe_connection['pe_ip']} remote-as {pe_connection['pe_asn']}\n"
    config += " !\n address-family ipv4\n"
    config += f"  network {loopback_ip.split()[0]} mask 255.255.255.255\n"
    subnet = ipaddress.ip_network(f"{pe_connection['interface_ip']}/30", strict=False)
    config += f"  network {subnet.network_address} mask 255.255.255.252\n"
    config += f"  neighbor {pe_connection['pe_ip']} activate\n"
    config += " exit-address-family\n!\n"
    
    config += "ip forward-protocol nd\n!\n!\nno ip http server\nno ip http secure-server\n!\n!\n!\n"
    config += "!\n" if router_name != "CE1-1" else ""
    config += "control-plane\n!\nline con 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\n!\n"
    config += "line aux 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\n!\n"
    config += "line vty 0 4\n login\n!\n!\nend\n"
    
    return config

def generate_configurations(network_intent):
    """GÃ©nÃ¨re toutes les configurations"""
    configurations = {}
    network = network_intent["network"]
    
    loopbacks = {
        name: {"loopback": router["loopback"]} 
        for name, router in network["routers"].items() if router["type"] in ["PE", "P"]
    }

    for router_name, router_data in network["routers"].items():
        if router_data["type"] in ["PE", "P"]:
            peers = {name: data for name, data in loopbacks.items() if name != router_name}
            ces = []
            if router_data["type"] == "PE":
                for intf, intf_data in router_data["interfaces"].items():
                    if "vrf" in intf_data:
                        ce_name = next(
                            (name for name, data in network["routers"].items() 
                             if data["type"] == "CE" and 
                             any(i["subnet"] == intf_data["subnet"] for i in data["interfaces"].values())),
                            None
                        )
                        if ce_name:
                            ces.append({
                                "vrf": intf_data["vrf"],
                                "ip": intf_data["ip"].split()[0],
                                "asn": network["routers"][ce_name]["asn"]
                            })
            
            config = generate_pe_config(router_name, router_data, network["asn"], peers, ces, network)
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
    
    return configurations



dicoCorrespondance = {
    "PE1": {"idRouter": "b2204a02-d9f5-401a-aeb0-b2520ca857eb", "id": "i1"}, 
    "P2": {"idRouter": "537e5ce3-fa03-4673-ab2b-061003d20734", "id": "i2"},
    "P3": {"idRouter": "00e8888b-4998-4e7a-89f2-80bc51884d63", "id": "i3"},   
    "PE2": {"idRouter": "d41540eb-2502-4e92-9617-7aea57fb7c38", "id": "i4"},   
    "CE1-1": {"idRouter": "4a599c6b-87a7-461b-a6db-0155bfd9d864", "id": "i5"},   
    "CE2-1": {"idRouter": "66bae736-2efa-4f45-8a11-325263fa63ee", "id": "i6"},   
    "CE1-2": {"idRouter": "c3193deb-0419-4cb1-80a9-ea32e140dc36", "id": "i7"},   
    "CE2-2": {"idRouter": "c028ed50-0163-4b0f-982a-4d1e334bcfa7", "id": "i8"},
    "PE3": {"idRouter": "4c2a7c29-5cba-4830-8b35-a5eec68b1706", "id":"i9"},
    "CE1-3": {"idRouter": "b51d121f-8651-45e1-a2b3-d5377bd6ce56", "id":"i10"},
    "CE2-3": {"idRouter": "ed983761-8696-4ffa-b14f-6370b2223d80", "id":"i11"}
}



def save_configurations(configurations, path):
    """Enregistre les configurations dans des fichiers"""
    for router_name, config in configurations.items():
        full_dir = os.path.join(path, dicoCorrespondance[router_name]["idRouter"],"configs")
        os.makedirs(full_dir, exist_ok=True)
        output_path = os.path.join(full_dir, f"{dicoCorrespondance[router_name]["id"]}_startup-config.cfg")
        with open(output_path, "w", encoding='utf-8') as f:
            f.write(config)

def main(path):
    intent = load_intent_file("intent-file.json")
    intent = calculate_ips(intent)
    configs = generate_configurations(intent)
    save_configurations(configs, path)
    print("\nGénération des configurations terminée!")

if __name__ == "__main__":
    main(sys.argv[1])