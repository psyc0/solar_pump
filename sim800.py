import time
import json

try:
    import logging
    logger = logging.getLogger(__name__)
except ImportError:
    try:
        import logger
    except ImportError:
        class Logger(object):
            level = 'INFO'

            @classmethod
            def debug(cls, text):
                if cls.level == 'DEBUG':
                    print('DEBUG:', text)

            @classmethod
            def info(cls, text):
                print('INFO:', text)

            @classmethod
            def warning(cls, text):
                print('WARN:', text)
        logger = Logger()


class GenericATError(Exception):
    pass


class ModemTimeout(Exception):
    pass


class Response(object):
    def __init__(self, status_code, content):
        self.status_code = int(status_code)
        self.content = content


class Modem(object):
    def __init__(self, 
                 uart=None, 
                 modem_pwkey_pin=None, 
                 modem_rst_pin=None, 
                 modem_power_on_pin=None, 
                 modem_tx_pin=None, 
                 modem_rx_pin=None):
        
        self.modem_pwkey_pin = modem_pwkey_pin
        self.modem_rst_pin = modem_rst_pin
        self.modem_power_on_pin = modem_power_on_pin
        self.modem_tx_pin = modem_tx_pin
        self.modem_rx_pin = modem_rx_pin
        self.uart = uart
        self.ppp = None
        self.initialized = False
        self.modem_info = None
        self.ssl_available = None
        self.modem_pwkey_pin_obj = None
        self.modem_rst_pin_obj = None
        self.modem_power_on_pin_obj = None

    def initialize(self):
        logger.debug('Initializing modem...')
        if not self.uart:
            from machine import UART, Pin

            # Pin initialization
            self.modem_pwkey_pin_obj = Pin(self.modem_pwkey_pin, Pin.OUT) if self.modem_pwkey_pin else None
            self.modem_rst_pin_obj = Pin(self.modem_rst_pin, Pin.OUT) if self.modem_rst_pin else None
            self.modem_power_on_pin_obj = Pin(self.modem_power_on_pin, Pin.OUT) if self.modem_power_on_pin else None

            # Status setup
            if self.modem_pwkey_pin_obj:
                self.modem_pwkey_pin_obj.value(0)
            if self.modem_rst_pin_obj:
                self.modem_rst_pin_obj.value(1)
            if self.modem_power_on_pin_obj:
                self.modem_power_on_pin_obj.value(1)

            # Setup UART
            self.uart = UART(1, 9600, timeout=1000, rx=self.modem_tx_pin, tx=self.modem_rx_pin)
            # self.uart = UART(1, 115200, timeout=1000, rx=self.modem_tx_pin, tx=self.modem_rx_pin)

        # Test AT commands
        retries = 0
        while True:
            try:
                self.modem_info = self.execute_at_command('modeminfo')
            except:
                retries += 1
                if retries < 3:
                    logger.debug('Error in getting modem info, retrying.. (#{})'.format(retries))
                    time.sleep(3)
                else:
                    raise
            else:
                break

        logger.debug('Ok, modem "{}" is ready and accepting commands'.format(self.modem_info))
        self.initialized = True
        self.ssl_available = self.execute_at_command('checkssl') == '+CIPSSL: (0-1)'

    def execute_at_command(self, command, data=None, clean_output=True):
        commands = {
                    'modeminfo':   {'string': 'ATI', 'timeout': 3, 'end': 'OK'},
                    'fwrevision':  {'string': 'AT+CGMR', 'timeout': 3, 'end': 'OK'},
                    'battery':     {'string': 'AT+CBC', 'timeout': 3, 'end': 'OK'},
                    'scan':        {'string': 'AT+COPS=?', 'timeout': 60, 'end': 'OK'},
                    'network':     {'string': 'AT+COPS?', 'timeout': 3, 'end': 'OK'},
                    'signal':      {'string': 'AT+CSQ', 'timeout': 3, 'end': 'OK'},
                    'checkreg':    {'string': 'AT+CREG?', 'timeout': 3, 'end': 'OK'},
                    'setapn':      {'string': 'AT+SAPBR=3,1,"APN","{}"'.format(data), 'timeout': 3, 'end': 'OK'},
                    'setuser':     {'string': 'AT+SAPBR=3,1,"USER","{}"'.format(data), 'timeout': 3, 'end': 'OK'},
                    'setpwd':      {'string': 'AT+SAPBR=3,1,"PWD","{}"'.format(data), 'timeout': 3, 'end': 'OK'},
                    'initgprs':    {'string': 'AT+SAPBR=3,1,"Contype","GPRS"', 'timeout': 3, 'end': 'OK'},
                    'opengprs':    {'string': 'AT+SAPBR=1,1', 'timeout': 3, 'end': 'OK'},
                    'getbear':     {'string': 'AT+SAPBR=2,1', 'timeout': 3, 'end': 'OK'},
                    'inithttp':    {'string': 'AT+HTTPINIT', 'timeout': 3, 'end': 'OK'},
                    'sethttp':     {'string': 'AT+HTTPPARA="CID",1', 'timeout': 3, 'end': 'OK'},
                    'checkssl':    {'string': 'AT+CIPSSL=?', 'timeout': 3, 'end': 'OK'},
                    'enablessl':   {'string': 'AT+HTTPSSL=1', 'timeout': 3, 'end': 'OK'},
                    'disablessl':  {'string': 'AT+HTTPSSL=0', 'timeout': 3, 'end': 'OK'},
                    'initurl':     {'string': 'AT+HTTPPARA="URL","{}"'.format(data), 'timeout': 3, 'end': 'OK'},
                    'doget':       {'string': 'AT+HTTPACTION=0', 'timeout': 3, 'end': '+HTTPACTION'},
                    'setcontent':  {'string': 'AT+HTTPPARA="CONTENT","{}"'.format(data), 'timeout': 3, 'end': 'OK'},
                    'postlen':     {'string': 'AT+HTTPDATA={},5000'.format(data), 'timeout': 3, 'end': 'DOWNLOAD'},
                    'dumpdata':    {'string': data, 'timeout': 1, 'end': 'OK'},
                    'dopost':      {'string': 'AT+HTTPACTION=1', 'timeout': 3, 'end': '+HTTPACTION'},
                    'getdata':     {'string': 'AT+HTTPREAD', 'timeout': 3, 'end': 'OK'},
                    'closehttp':   {'string': 'AT+HTTPTERM', 'timeout': 3, 'end': 'OK'},
                    'closebear':   {'string': 'AT+SAPBR=0,1', 'timeout': 3, 'end': 'OK'},
                    'syncbaud':    {'string': 'AT', 'timeout': 3, 'end': 'OK'},
                    'reset':       {'string': 'ATZ', 'timeout': 3, 'end': 'OK'},
                    'disconnect':  {'string': 'ATH', 'timeout': 20, 'end': 'OK'},  # Use "NO CARRIER" here?
                    'checkpin':    {'string': 'AT+CPIN?', 'timeout': 3, 'end': 'OK'},
                    'nosms':       {'string': 'AT+CNMI=0,0,0,0,0', 'timeout': 3, 'end': 'OK'},
                    'ppp_setapn':  {'string': 'AT+CGDCONT=1,"IP","{}"'.format(data), 'timeout': 3, 'end': 'OK'},
                    'ppp_connect': {'string': 'AT+CGDATA="PPP",1', 'timeout': 3, 'end': 'CONNECT'},
                    'rfon':        {'string': 'AT+CFUN=1', 'timeout': 3, 'end': 'OK'},
                    'rfoff':       {'string': 'AT+CFUN=4', 'timeout': 3, 'end': 'OK'},
                    'echoon':      {'string': 'ATE1', 'timeout': 3, 'end': 'OK'},
                    'echooff':     {'string': 'ATE0', 'timeout': 3, 'end': 'OK'},
        }

        # Sanity checks
        if command not in commands:
            command_string = command
            excpected_end = 'OK'
            timeout = 3
        else:
            # Support vars
            command_string = commands[command]['string']
            excpected_end = commands[command].get('end', 'OK')
            timeout = commands[command].get('timeout', 3)
        processed_lines = 0

        # Execute the AT command
        command_string_for_at = "{}\r\n".format(command_string)
        logger.debug('Writing AT command "{}"'.format(command_string_for_at.encode('utf-8')))
        self.uart.write(command_string_for_at)

        # Support vars
        pre_end = True
        output = ''
        empty_reads = 0

        while True:
            line = self.uart.readline()
            if not line:
                time.sleep(1)
                empty_reads += 1
                if empty_reads > timeout:
                    raise Exception('Timeout for command "{}" (timeout={})'.format(command, timeout))
            else:
                logger.debug('Read "{}"'.format(line))

                # Convert line to string
                line_str = line.decode('utf-8')

                # Do we have an error?
                if line_str == 'ERROR\r\n':
                    raise GenericATError('Got generic AT error')

                # If we had a pre-end, do we have the expected end?
                if line_str == '{}\r\n'.format(excpected_end):
                    logger.debug('Detected exact end')
                    break
                if pre_end and line_str.startswith('{}'.format(excpected_end)):
                    logger.debug('Detected startwith end (and adding this line to the output too)')
                    output += line_str
                    break

                # Do we have a pre-end?
                if line_str == '\r\n':
                    pre_end = True
                    logger.debug('Detected pre-end')
                else:
                    pre_end = False

                # Keep track of processed lines and stop if exceeded
                processed_lines += 1

                # Save this line unless in particular conditions
                if command == 'getdata' and line_str.startswith('+HTTPREAD:'):
                    pass
                else:
                    output += line_str

        # Remove the command string from the output
        output = output.replace(command_string+'\r\r\n', '')

        # ..and remove the last \r\n added by the AT protocol
        if output.endswith('\r\n'):
            output = output[:-2]

        # Also, clean output if needed
        if clean_output:
            output = output.replace('\r', '')
            output = output.replace('\n\n', '')
            if output.startswith('\n'):
                output = output[1:]
            if output.endswith('\n'):
                output = output[:-1]

        logger.debug('Returning "{}"'.format(output.encode('utf8')))
        return output

    def get_info(self):
        output = self.execute_at_command('modeminfo')
        return output

    def battery_status(self):
        output = self.execute_at_command('battery')
        return output

    def scan_networks(self):
        networks = []
        output = self.execute_at_command('scan')
        pieces = output.split('(', 1)[1].split(')')
        for piece in pieces:
            piece = piece.replace(',(', '')
            subpieces = piece.split(',')
            if len(subpieces) != 4:
                continue
            networks.append({'name': json.loads(subpieces[1]),
                             'shortname': json.loads(subpieces[2]),
                             'id': json.loads(subpieces[3])})
        return networks

    def get_current_network(self):
        output = self.execute_at_command('network')
        network = output.split(',')[-1]
        if network.startswith('"'):
            network = network[1:]
        if network.endswith('"'):
            network = network[:-1]
        # If after filtering we did not filter anything: there was no network
        if network.startswith('+COPS'):
            return None
        return network

    def get_signal_strength(self):
        # See more at https://m2msupport.net/m2msupport/atcsq-signal-quality/
        output = self.execute_at_command('signal')
        signal = int(output.split(':')[1].split(',')[0])
        signal_ratio = float(signal)/float(30)  # 30 is the maximum value (2 is the minimum)
        return signal_ratio

    def get_ip_addr(self):
        output = self.execute_at_command('getbear')
        output = output.split('+')[-1]  # Remove potential leftovers in the buffer before the "+SAPBR:" response
        pieces = output.split(',')
        if len(pieces) != 3:
            raise Exception('Cannot parse "{}" to get an IP address'.format(output))
        ip_addr = pieces[2].replace('"', '')
        if len(ip_addr.split('.')) != 4:
            raise Exception('Cannot parse "{}" to get an IP address'.format(output))
        if ip_addr == '0.0.0.0':
            return None
        return ip_addr

    def connect(self, apn, user='', pwd=''):
        if not self.initialized:
            raise Exception('Modem is not initialized, cannot connect')

        # Are we already connected?
        if self.get_ip_addr():
            logger.debug('Modem is already connected, not reconnecting.')
            return

        # Closing bearer if left opened from a previous connect gone wrong:
        logger.debug('Trying to close the bearer in case it was left open somehow..')
        try:
            self.execute_at_command('closebear')
        except GenericATError:
            pass

        # First, init gprs
        logger.debug('Connect step #1 (initgprs)')
        self.execute_at_command('initgprs')

        # Second, set the APN
        logger.debug('Connect step #2 (setapn)')
        self.execute_at_command('setapn', apn)
        self.execute_at_command('setuser', user)
        self.execute_at_command('setpwd', pwd)

        # Then, open the GPRS connection.
        logger.debug('Connect step #3 (opengprs)')
        self.execute_at_command('opengprs')

        # Ok, now wait until we get a valid IP address
        retries = 0
        max_retries = 5
        while True:
            retries += 1
            ip_addr = self.get_ip_addr()
            if not ip_addr:
                retries += 1
                if retries > max_retries:
                    raise Exception('Cannot connect modem as could not get a valid IP address')
                logger.debug('No valid IP address yet, retrying... (#')
                time.sleep(1)
            else:
                break

    def disconnect(self):
        try:
            self.execute_at_command('closebear')
        except GenericATError:
            pass

        ip_addr = self.get_ip_addr()
        if ip_addr:
            raise Exception('Error, we should be disconnected but we still have an IP address ({})'.format(ip_addr))

    def http_request(self, url, mode='GET', data=None, content_type='application/json'):
        assert url.startswith('http'), 'Unable to handle communication protocol for URL "{}"'.format(url)
        if not self.get_ip_addr():
            raise Exception('Error, modem is not connected')

        # Close the http context if left open somehow
        logger.debug('Close the http context if left open somehow...')
        try:
            self.execute_at_command('closehttp')
        except GenericATError:
            pass

        # First, init and set http
        logger.debug('Http request step #1.1 (inithttp)')
        self.execute_at_command('inithttp')
        logger.debug('Http request step #1.2 (sethttp)')
        self.execute_at_command('sethttp')

        # Do we have to enable ssl as well?
        if self.ssl_available:
            if url.startswith('https://'):
                logger.debug('Http request step #1.3 (enablessl)')
                self.execute_at_command('enablessl')
            elif url.startswith('http://'):
                logger.debug('Http request step #1.3 (disablessl)')
                self.execute_at_command('disablessl')
        else:
            if url.startswith('https://'):
                raise NotImplementedError("SSL is only supported by firmware revisions >= R14.00")

        # Second, init and execute the request
        logger.debug('Http request step #2.1 (initurl)')
        self.execute_at_command('initurl', data=url)

        if mode == 'GET':

            logger.debug('Http request step #2.2 (doget)')
            output = self.execute_at_command('doget')
            response_status_code = output.split(',')[1]
            logger.debug('Response status code: "{}"'.format(response_status_code))

        elif mode == 'POST':

            logger.debug('Http request step #2.2 (setcontent)')
            self.execute_at_command('setcontent', content_type)

            logger.debug('Http request step #2.3 (postlen)')
            self.execute_at_command('postlen', len(data))

            logger.debug('Http request step #2.4 (dumpdata)')
            self.execute_at_command('dumpdata', data)

            logger.debug('Http request step #2.5 (dopost)')
            output = self.execute_at_command('dopost')
            response_status_code = output.split(',')[1]
            logger.debug('Response status code: "{}"'.format(response_status_code))

        else:
            raise Exception('Unknown mode "{}'.format(mode))

        # Third, get data
        logger.debug('Http request step #4 (getdata)')
        response_content = self.execute_at_command('getdata', clean_output=False)

        logger.debug(response_content)

        # Then, close the http context
        logger.debug('Http request step #4 (closehttp)')
        self.execute_at_command('closehttp')

        return Response(status_code=response_status_code, content=response_content)

    def ppp_connect(self):

        if not self.initialized:
            raise Exception('Modem is not initialized, cannot connect')

        self.execute_at_command('syncbaud')
        self.execute_at_command('reset')
        self.execute_at_command('echooff')
        self.execute_at_command('rfon')
        self.execute_at_command('checkpin')
        self.execute_at_command('checkreg')
        self.execute_at_command('nosms')
        self.execute_at_command('ppp_setapn', 'm2m.tele2.com')
        self.execute_at_command('ppp_connect')

        import network
        self.ppp = network.PPP(self.uart)
        self.ppp.active(True)
        self.ppp.connect(authmode=self.ppp.AUTH_CHAP, username="", password="")

    def ppp_disconnect(self):
        self.ppp.active(False)
        self.execute_at_command('syncbaud')
        self.execute_at_command('disconnect')
        self.execute_at_command('rfoff')
        self.execute_at_command('echoon')
