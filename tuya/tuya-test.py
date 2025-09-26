import tinytuya

"""
OUTLET Device
"""
d = tinytuya.Device('DEVICE_ID_HERE', 'IP_ADDRESS_HERE', 'LOCAL_KEY_HERE', version=3.3)
data = d.status()  

# Show status and state of first controlled switch on device
print('Dictionary %r' % data)
print('State (bool, true is ON) %r' % data['dps']['1'])  