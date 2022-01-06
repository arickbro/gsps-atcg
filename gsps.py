import serial
import sqlite3
import serial.tools.list_ports
from gsps_helper import *
from serial_reader import *
from messaging.sms import SmsSubmit
from messaging.sms import SmsDeliver

import time
import logging
import threading
import glob
import re


logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)

class GSPS:

    def __init__(self):
        self.isConnected = False
        self.atcgOnGoing = False
        self.conn = False
        self.LastCallId = None
        self.wss = []
        self.ports = []
        self.SMSQueue = []
        self.deviceInfo = {
            'IMSI':None,
            'IMEI':None,
            'model':None,
            'gpsStatus':None,
            'gpsLatitude':None,
            'gpsLongitude':None,
            'cellIdentity':None,
            'locationAreaCode':None,
            'gpsTimestamp':None,
            'registered':None,
            'registrationInfo':None,
        }
        self.status = {
            'battery':None,
            'isSmsFull':None,
            'signalStrength':None,
            'service':None,
            'sounder':None,
            'smsRec':None,
            'callInProgress':None,
            'tx':None,
            'isRoaming':None,
            'ongoingCall':None,
            'lastCall':None,
            'prov1':None,
            'prov2':None,
            'mcc':None,
            'cid':None,
        }
        
        self.lock = threading.Lock() 
        self.signal ={'ts':0,'rssi':None, 'ber':None}
        
        self.gb = 0
        self.config = {}
        self.db = sqlite3.connect('/home/arickbro/vscode/gsps-atcg/isatc.db',check_same_thread=False)
        self.get_config_from_db()

        #make sure the UT ready
        time.sleep(10)

        self.connect()
        self.daemon = threading.Thread(target=self.keep_alive, args=())
        self.daemon.start()

        self.thread = ReaderThread(self)
        self.thread.start()

    def get_port(self):
        self.ports = serial.tools.list_ports.comports()
        regex = r"isatphone|isat|oceana|terra"
        return "/dev/inmarsat"
        
        for port, desc, hwid in sorted(self.ports):
            desc = desc.lower()
            print("{}: {} [{}]".format(port, desc, hwid))
            if desc.find("modem")  != -1 and re.search(regex, desc, re.IGNORECASE | re.DOTALL):
                return port
        return False

    def get_config_from_db(self):
        result = {"error":"","data":{}}
        try:
            cursor = self.db.execute("SELECT * from isatc_config")
            for row in cursor:
                if row[2] == "int":
                    self.config[row[0]] = int(row[1])
                elif row[2] == "bytes":
                    self.config[row[0]] = bytes(row[1], 'utf-8')
                else:
                    self.config[row[0]]  = None if row[1].strip() == '' else row[1].strip()
                result['data'][row[0]] = row[1]

        except Exception as e:
            result["error"] = str(e)

        return result

    def set_config(self,config):
        result = {"error":""}
        try:
            for key in config:
                self.db.execute("update gsps_config set config_value=? where config_name=?",(config[key],key))
                self.db.commit()
            self.get_config_from_db()
        except Exception as e:
            result["error"] = str(e)

        return result

    def get_historical_snr(self,param):
        result = {"error":"","data":[]}
        try:
            sql = "select (timestamp/?)*? as ts, avg(signal_level), sum(ber) as snr from gsps_snr_ber where timestamp >= ? and timestamp < ? group by ts "
            cursor = self.db.execute(sql, (param['bucket'],param['bucket'],param['start'],param['end']))
            for row in cursor:
                result["data"].append(row)
        except Exception as e:
            result["error"] = str(e)
        return result

    def get_calls(self,param):

        result = {"error":"","columns":["timestamp","call_id","disc_cause","call_stat","dest_num"], "rows":[],"count":None}
        sql = "select count(timestamp) from call_log where timestamp >= ? and timestamp < ? "
        try:
            cursor = self.db.execute(sql, (param['start'],param['end']))
            result["output"] = cursor.fetchone()[0]
            
            sql = "select "+",".join(result["columns"])+" from call_log where timestamp >= ? and timestamp < ?  LIMIT ? OFFSET ?"
            cursor = self.db.execute(sql, (param['start'],param['end'],param['limit'],param['offset']))
            for row in cursor:
                result["data"].append(row)
        except Exception as e:
            result["error"] = str(e)
        return result

    def get_sms(self,param):

        result = {"error":"","columns":["timestamp","sms_id","type","dest","content","content_length","status"], "rows":[],"count":None}
        sql = "select count(timestamp) from sms_log where timestamp >= ? and timestamp < ? "
        try:
            cursor = self.db.execute(sql, (param['start'],param['end']))
            result["output"] = cursor.fetchone()[0]
            
            sql = "select "+",".join(result["columns"])+" from sms_log where timestamp >= ? and timestamp < ?  LIMIT ? OFFSET ?"
            cursor = self.db.execute(sql, (param['start'],param['end'],param['limit'],param['offset']))
            for row in cursor:
                result["data"].append(row)
        except Exception as e:
            result["error"] = str(e)
        return result
    
    def connect(self):
        self.isConnected = False
        try:
        
            if self.conn:
                self.conn.close()
                
            if self.config["serial"] == 'auto':  
                port = self.get_port()
                if port == False:
                    logging.error('port not found ')
                    time.sleep(5)
                    return False
            else:
                port = self.config["serial"]
            
            logging.info('connecting to '+str(port))
            
            self.lock.acquire()
            self.conn = serial.Serial(
                port=port, baudrate=self.config["baudrate"], 
                timeout=self.config["read_timeout"], 
                write_timeout=self.config["write_timeout"],
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS
            )

            if self.conn.is_open:
                logging.info('connected')
                self.lock.release()
                self.isConnected = True
                self.iniatialRead = True
                self.get_ut_parameter()
      
                return True
        except Exception as e:
            if self.lock.locked():
                self.lock.release()
            logging.error(str(e))
        
        return False 


    def write(self,data,expect=False):
        string =""
        self.lock.acquire() 
        
        try:
            logging.debug(data.decode('utf-8'))
            
            if expect == False:
                #fire and forget, and let the parsing serial handle the job
                self.conn.write(data)
            else:
                #write and expect for a return
                self.conn.reset_input_buffer()
                self.conn.write(data)
                string = self.conn.read_until(expect).decode('ascii')
        except Exception as e:
            if self.lock.locked():
                self.lock.release()
            logging.error(str(e))
            time.sleep(5)
            self.connect()

        if self.lock.locked():  
            self.lock.release()

        erorr =  singleLine(r"ERROR: (\d+)",string)

        return {'data':string,'error':erorr}
        
    def get_ut_parameter(self):
        if self.conn.isOpen() :
            self.write(b"AT+CNMI=1,2,0,0,0\r\n")
            time.sleep(0.5)
            self.write(b"AT+CREG=2\r\n")
            time.sleep(0.5)
            self.write(b"AT+SKCTIME\r\n")
            time.sleep(0.5)
            self.write(b"AT+CIMI\r\n")
            time.sleep(0.5)
            self.write(b"AT+SKMODEL?\r\n")
            time.sleep(0.5)
            self.write(b"AT+CIND?\r\n")
            time.sleep(0.5)
            self.write(b"AT+CREG?\r\n")
            time.sleep(0.5)
            self.write(b"AT+SKRGPSPOS=?\r\n")
            time.sleep(0.5)
            self.write(b"AT+CGSN\r\n")
            time.sleep(0.5)

    def fetch_snr(self):
        self.write(b"AT+CSQ\r\n")


    def make_call(self,dest,timeout=False):
        string = "ATD"+dest+";" + '\r\n'
        self.write(bytes(string,'utf-8'))
        sql ="INSERT INTO `call_log`( `dest_num`, `call_stat`,`disc_cause`,timestamp) VALUES (?,?,?,?)"
        self.db.execute(sql,(dest,0,0,int(time.time())))
        self.db.commit()
        self.LastCallId =  self.db.cursor().lastrowid

        if timeout != False:                               
            time.sleep(timeout)
            self.write(b"ATH\r\n")

    def make_sms(self,dest,content):
        sms = SmsSubmit(dest,content)
        for pdu in sms.to_pdu():
            smsString = 'AT+CMGS=%d\r' % pdu.length
            self.write(bytes(smsString,'utf-8'))
            time.sleep(0.1)
            smsString = '%s\x1a' % pdu.pdu
            self.write(bytes(smsString,'utf-8'), "CMGS")

    def keep_alive(self):
        currentEpoch = 0
        lastEpoch = 0
        lastEpochCall = 0
        logging.debug("keep alive running")

        while True:
                    
            try:
                currentEpoch = int(time.time())
                '''read signal strength every 10 secs'''
                if currentEpoch - lastEpoch >= self.config["signal_read_interval"] and self.atcgOnGoing == False :
                    lastEpoch = currentEpoch
                    logging.debug("check signal level")
                    self.fetch_snr()
                    self.broadcast("lorem")
                ''' make a call every configurable interval '''
                
                if self.config["enable_atcg"] and  currentEpoch - lastEpochCall >= self.config["atcg_interval"]    :
                    lastEpochCall = currentEpoch
                    self.make_call(self.config["atcg_dest"])
                    self.atcgOnGoing = True
                
            except Exception as e:
                logging.error(str(e))

            time.sleep(1)



    def get_device_info(self):
        self.deviceInfo['isSerialConnected'] = self.isConnected
        return {"error":"","data":self.deviceInfo}

    def add_sms_to_queue(self,dest,content):
        self.SMSQueue.push({'dest':dest,'content':content})

    def power_cycle(self):
        self.conn.write(b'AT+SKCKPD="E",1\r\n')
        return "success"
        
    def hangup(self):
        self.conn.write(b"ATH\r\n")
    
    def broadcast(self,data):
        removed = []
        for ws in self.wss:
            try:
                ws.send(data)
            except Exception as e:
                logging.warning(str(e))
                removed.append(ws)

        for i in removed:
            self.wss.remove(i)

    def add_to(self,sock):
        self.wss.append(sock)

    def get_status(self):
        return {"error":"","data":self.status}

    def get_snr(self):
        return {"error":"","data":self.signal}