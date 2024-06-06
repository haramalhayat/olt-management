import paramiko
import time
import re

def login_to_olt(host, port, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=int(port), username=username, password=password)
    
    tn = client.invoke_shell()
    time.sleep(1)
    tn.send('enable\n')
    time.sleep(1)
    tn.send('config\n')
    time.sleep(1)
    return tn

def execute_command(tn, command, delay=3):
    tn.send(command + "\n")
    time.sleep(delay)
    output = tn.recv(65535).decode('ascii')
    print(output)
    return output

def save_configuration(tn):
    tn.send("save\n")
    time.sleep(1)
    output = tn.recv(65535).decode('ascii')
    print(output)
    
    if "{ <cr>|configuration<K>|data<K> }:" in output:
        tn.send("\n")  # or "data\n" if that's what you want to save
        time.sleep(1)
        output = tn.recv(65535).decode('ascii')
        print(output)

    end_time = time.time() + 86  # Set the timeout for 86 seconds
    while time.time() < end_time:
        if "The data of" in output and "board is saved" in output:
            print("Configuration has been saved successfully.")
            return
        time.sleep(5)  # Wait for 5 seconds before checking again
        output = tn.recv(65535).decode('ascii')
        print(output)

    print("Save operation timed out.")

def parse_ont_list(output):
    ont_list = []
    pattern = re.compile(r'Number\s+:\s+(\d+).*?F/S/P\s+:\s+0/(\d+)/(\d+).*?Ont SN\s+:\s+([A-F0-9]+)', re.DOTALL)
    matches = pattern.findall(output)
    
    for match in matches:
        ont_list.append({
            'number': match[0],
            'slot': match[1],
            'pon': match[2],
            'sn': match[3]
        })
    
    return ont_list

def display_ont_list(ont_list):
    for ont in ont_list:
        print(f"Number: {ont['number']}, Slot: {ont['slot']}, PON: {ont['pon']}, SN: {ont['sn']}")

def add_ont(tn):
    output = execute_command(tn, "display ont autofind all")
    print("Output of the 'display ont autofind all' command:")
    print(output)

    if "Failure: The automatically found ONTs do not exist" in output:
        print("No ONTs found. Exiting the session.")
        return

    ont_list = parse_ont_list(output)
    if not ont_list:
        print("No ONTs found to add.")
        return

    display_ont_list(ont_list)
    ont_number = input("Enter the ONT number to add: ").strip()
    selected_ont = next((ont for ont in ont_list if ont['number'] == ont_number), None)

    if not selected_ont:
        print("Invalid ONT number.")
        return

    slot_value = selected_ont['slot']
    pon_value = selected_ont['pon']
    id_value = selected_ont['sn']

    execute_command(tn, f"interface gpon 0/{slot_value}")
    time.sleep(3)
    tn.send(f"ont add {pon_value} sn-auth {id_value} omci ont-lineprofile-id 1 ont-srvprofile-id 1\n")
    tn.send("\n")
    time.sleep(3)
    output = tn.recv(65535).decode('ascii')
    print(f"Output of the 'ont add {pon_value} sn-auth {id_value} omci ont-lineprofile-id 1 ont-srvprofile-id 1' command:")
    print(output)

    onu_match = re.search(r"ONTID\s*:\s*(\d+)", output)
    if not onu_match:
        print("Failed to parse ONU ID from the output.")
        print("Debug Output:")
        print(output)  # Print the entire output for debugging
        return

    onu_value = onu_match.group(1)
    execute_command(tn, "quit")
    execute_command(tn, f"service-port vlan 9 gpon 0/{slot_value}/{pon_value} ont {onu_value} gemport 1 multi-service user-vlan 9")
    tn.send("\n")
    time.sleep(3)
    execute_command(tn, f"service-port vlan 10 gpon 0/{slot_value}/{pon_value} ont {onu_value} gemport 2 multi-service user-vlan 10")
    tn.send("\n")
    time.sleep(3)
    # Save the configuration
    save_configuration(tn)

def delete_ont(tn):
    output = execute_command(tn, "display ont autofind all")
    print("Output of the 'display ont autofind all' command:")
    print(output)

    ont_list = parse_ont_list(output)
    if not ont_list:
        print("No ONTs found to delete.")
        id_value = input("Enter the SERIAL ID field value manually: ").strip()
    else:
        display_ont_list(ont_list)
        ont_number = input("Enter the ONT number to delete: ").strip()
        selected_ont = next((ont for ont in ont_list if ont['number'] == ont_number), None)
        if not selected_ont:
            print("Invalid ONT number.")
            return
        id_value = selected_ont['sn']

    output = execute_command(tn, f"display ont info by-sn {id_value}")
    print("Output of the 'display ont info by-sn' command:")
    print(output)
    tn.send("Q\n")
    time.sleep(1)

    # Parse slot, pon, and ONU ID from the output
    match = re.search(r"F/S/P\s+:\s+0/(\d+)/(\d+)", output)
    onu_match = re.search(r"ONT-ID\s+:\s+(\d+)", output)
    if not match or not onu_match:
        print("Failed to parse slot, PON, or ONU ID from the output.")
        return

    slot_value = match.group(1)
    pon_value = match.group(2)
    onu_value2 = onu_match.group(1)

    tn.send(f"display service-port port 0/{slot_value}/{pon_value} ont {onu_value2}\n")
    tn.send("\n")
    time.sleep(3)
    output = tn.recv(65535).decode('ascii')
    print(f"Output of the 'display service-port port 0/{slot_value}/{pon_value} ont {onu_value2}' command:")
    print(output)

    # Parse service-port ID values from the output
    undo_id_matches = re.findall(r"\s+(\d+)\s+\d+\s+common\s+gpon\s+0/\d+\s+/\d+\s+\d+\s+\d+\s+vlan", output, re.MULTILINE)
    if not undo_id_matches:
        print("Failed to parse service-port ID values from the output.")
        undo_id_matches = input("Enter the UNDO ID field values separated by (.): ").strip().split('.')

    for id_undo_value in undo_id_matches:
        tn.send(f"undo service-port {id_undo_value.strip()}\n")
        time.sleep(1)
        tn.send("\n")
        time.sleep(1)

    execute_command(tn, f"interface gpon 0/{slot_value}")
    execute_command(tn, f"ont delete {pon_value} {onu_value2}")
    execute_command(tn, "quit")
    # Save the configuration
    #1save_configuration(tn)
    return

# Other parts of the script remain unchanged

def main():
    print(r"  ___  _    _ _____   _____ _____   _____ _____ ______ ___________ _____ ")
    print(r" / _ \| |  | /  ___| |_   _|_   _| /  ___/  __ \| ___ \_   _| ___ \_   _|")
    print(r"/ /_\ \ |  | \ `--.    | |   | |   \ `--.| /  \/| |_/ / | | | |_/ / | |  ")
    print(r"|  _  | |/\| |`--. \   | |   | |    `--. \ |    |    /  | | |  __/  | |  ")
    print(r"| | | \  /\  /\__/ /  _| |_  | |   /\__/ / \__/\| |\ \ _| |_| |     | |  ")
    print(r"\_| |_/\/  \/\____/   \___/  \_/   \____/ \____/\_| \_|\___/\_|     \_/  ")
    print(r"                                                                         ")
    host = "10.56.193.45"
    port = "22"  # Default port for SSH is 22
    username = "root"
    password = "Abcd1234"

    tn = login_to_olt(host, port, username, password)
    
    while True:
        action = input("Do you want to 1=(add) or 2=(delete) or 0=(exit) an ONT? (1/2/0): ").strip().lower()
        if action == "0":
            tn.close()
            break
        if action == "1":
            add_ont(tn)
        elif action == "2":
            delete_ont(tn)
        else:
            print("Invalid option. Please enter '1' or '2' or '0'.")

if __name__ == "__main__":
    main()