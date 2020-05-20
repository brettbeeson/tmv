
try:
    # required only for influx_stats
    import influxdb
    import pyrfc3339
    import uptime
    from gpiozero import CPUTemperature
    import socket
except ImportError as e:
    print(e)

    
def influx_stats_console():
    p = [{
        'measurement': 'status',
        'tags': {
            'magic_filename': magic_filename(),
            'hostname': socket.gethostname(),
        },
        'fields': {
            'load5': float(os.getloadavg()[2]),
            'soc_temp': float(100 * CPUTemperature().value),
            'uptime': float(uptime.uptime()),
            'lastboot': pyrfc3339.generator.generate(uptime.boottime(), accept_naive=True)
        }
    }]

    i = influxdb.InfluxDBClient(
        "live.phisaver.com", username="iot", password="imagine", database='iot')
    i.write_points(p)
