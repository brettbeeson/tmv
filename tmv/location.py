
try:
    # Get location via IP: heaps of dependacies
    # from ip2geotools.databases.noncommercial import DbIpCity
    # from requests import get        # Get location via IP
    # todo: find lightweight alt
    pass
except ImportError:
    pass

def nearby_city():
    """Find the nearest city to our IP address

    Requires:
        DbIpCity and ip2geotools. Could use tzupdate-method instead for fewer dependencies

    Returns:
        named tuple (city ,latitude, longnitude)
    """
    #public_ip = get('https://api.ipify.org').text
    #city = DbIpCity.get(public_ip, api_key='free')

    #return city

