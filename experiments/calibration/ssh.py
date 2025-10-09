import os
import re

import paramiko

nodes = (('node-0', 4, 'ondemand'),
         ('node-1', 4, 'ondemand'),
         ('node-2', 4, 'ondemand'),
         ('node-3', 16, 'powersave'),
         ('node-4', 16, 'powersave'),
         ('node-5', 16, 'powersave'),
        )


def get_ssh_client(node_name, username="rpiadmin"):

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname=node_name, username=username)
    except paramiko.AuthenticationException:
        print("Authentication failed.")
    except paramiko.SSHException as e:
        print(f"SSH error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

    return client


def execute_sudo_command(client, command, sudo_password):
    stdin, stdout, stderr = client.exec_command(command, get_pty=True)
    stdin.write(sudo_password + '\n')
    stdin.flush()

    output = stdout.read().decode('utf-8')
    errors = stderr.read().decode('utf-8')

    return output, errors


def validate_node_governor(client, node_name, core_count, governor):

    for i in range(core_count):
        command = f"cpupower -c {i} frequency-info -p"
        stdin, stdout, stderr = client.exec_command(command)
        
        output = stdout.read().decode('utf-8')
        errors = stderr.read().decode('utf-8')
        match = re.search(r'The governor \"(\S+)\"', output)
        if match:
            if match.group(1) != governor:
                raise Exception(f"Expected {governor} but found {match.group(1)}")
        else:
            raise Exception("No governor found")
        
        
def set_cpu_governor_to_performance(nodes=nodes, revert=False):
    """ Sets the governor to performance or reverts to default state.
    Will throw an exception if it cannot validate that settings were updated correctly."""
    
    sudo_password = os.environ["RPIADMIN_SUDO_PASSWORD"]
    
    for node in nodes:
        node_name, core_count, default_governor = node
        
        if revert:
            governor = default_governor
        else:
            governor = "performance"
        
        client = get_ssh_client(node_name)

        command = f"sudo cpupower frequency-set --governor {governor}"
        
        output, errors = execute_sudo_command(client, command, sudo_password)
        
        if errors:
            print(f"Errors setting {node_name}:\n", errors)

        validate_node_governor(client, node_name, core_count, governor)

        client.close()

            

