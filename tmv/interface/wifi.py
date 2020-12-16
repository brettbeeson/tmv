from  subprocess import run

def scan(interface='wlan0'):
    """ Run a wifi scan and return text with information

    Args:
        interface (str, optional): interface to use. Defaults to 'wlan0'.

    Raises:
        CalledProcessError: If wpa_cli returned non-zero

    Returns:
        str : text from wpa_cli scan_results
    """
    cl = ['wpa_cli', '-i', interface, 'scan']
    run(cl, encoding="UTF-8", check=True, capture_output=True)
    
    cl = ['wpa_cli', '-i', interface, 'scan_results']
    scan_results = run(cl, encoding="UTF-8",  check=True, capture_output=True)
    return scan_results.stdout

def reconfigure(interface='wlan0'):
    cl = ['wpa_cli', '-i', interface, 'reconfigure']
    r = run(cl, encoding="UTF-8", check=True, capture_output=True)
    print (r.stdout)
    return r.stdout
