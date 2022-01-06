import serial
import sqlite3
from gsps_helper import *
from messaging.sms import SmsSubmit
from messaging.sms import SmsDeliver

import time
import logging
import threading
import glob
import re


logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)

class ReaderThread(threading.Thread):
    def __init__(self, main_instance):
        super().__init__()
        self.main = main_instance

    def run(self):
        try:
            if self.main.conn.isOpen() :
                logging.info("reader connected") 
                while True:
                    tdata = self.main.conn.read().decode('ascii')
                    time.sleep(0.2)
                    if self.main.conn.inWaiting() > 0:
                        tdata += self.main.conn.read(self.main.conn.inWaiting()).decode('ascii')

                    if tdata.strip() != "":
                        self.parsing_serial(tdata)
            else:
                print("reader not connected")

        except Exception as e:
            ErrorString = str(e)
            logging.error(ErrorString)
            if ErrorString.find("device reports readiness to read but returned no data") != -1 or ErrorString.find("I/O error") != -1  :
                logging.info("exiting")
                time.sleep(5)
                self.main.connect()

    def parsing_serial(self,data):
        try:
            data = str(data)
            parts =  re.split(",|:|\r\n|\r",data.strip())
            parts = list(map(str.strip,parts))
            length = len(parts)
            
            MatchImei = re.search( r"(353\d{12})", data.strip(),re.MULTILINE)
            if MatchImei:
                self.main.deviceInfo["IMEI"] = MatchImei.group(1)

            if data.find("+SKRGPSPOS:") != -1:
                i = find_last(parts,"+SKRGPSPOS")
                if parts[i+1]=="1":
                    self.main.deviceInfo["gpsStatus"] = "Valid"
                else:
                    self.main.deviceInfo["gpsStatus"] = "Invalid"

                self.main.deviceInfo["gpsLatitude"] = parts[i+2]
                self.main.deviceInfo["gpsLongitude"] = parts[i+3]
                self.main.deviceInfo["gpsAltitude"] = parts[i+4]
                self.main.deviceInfo["gpsTimestamp"] = parts[i+5]+" "+parts[i+6]+":"+parts[i+7]+":"+parts[i+8]
                self.main.deviceInfo["gpsTimestamp"] = self.main.deviceInfo["gpsTimestamp"].replace("/","-")

                self.main.broadcast(self.main.deviceInfo)

            if data.find("+SKCTIME:") != -1:
                i = find_last(parts,"+SKCTIME")
                self.main.deviceInfo["gpsTimestamp"] = parts[i+1]+" "+parts[i+2]+":"+parts[i+3]+":"+parts[i+4]
                self.main.deviceInfo["gpsTimestamp"] = self.main.deviceInfo["gpsTimestamp"].replace("/","-")
                #os.system("date -s '"+info["LOC_TIME"]+"'")
                self.main.broadcast(self.main.deviceInfo)

            if data.find("RING") != -1:
                logging.info("ringing")
                self.main.broadcast({"respond":"ring","data":"Ringing"})

            if data.find("+CSQ:") != -1:
                i = find_last(parts,"+CSQ")

                ts = int(time.time())
                sqlstr="INSERT OR IGNORE INTO gsps_snr_ber (snr ,ber,timestamp) VALUES(?,?,?)"
                self.main.db.execute(sqlstr,(parts[i+1],parts[i+2],ts))
                self.main.db.commit()

                csq ={"respond":"csq","rssi":parts[i+1], "ber":parts[i+2]}
                self.main.signal = {'ts':ts,'rssi':parts[i+1], 'ber':parts[i+2]}
                self.main.broadcast(csq)
                    
            if data.find("+CMGS:") != -1:
                self.main.WaitingForCMGS = False
                i = find_last(parts,"+CMGS")
                logging.info("SMS:"+parts[i+1]+" LENGTH:"+parts[i+2])

                sqlstr="UPDATE sms_log set status = 'sent' where sms_id=?"
                self.main.db.execute(sqlstr,(self.main.LastSMSId,))
                self.main.db.commit()

                self.main.broadcast({"respond":"call_info","data":"SMS Sent"})

            if data.find("+CMT:") != -1:
                i = find_last(parts,"+CMT")
                sms = SmsDeliver(parts[i+3])

                sql = "INSERT INTO sms_log (type, dest, content,content_length,status) VALUES (?,?,?,?,?)"
                self.main.db.execute(sql, (0,sms.number,sms.text,parts[i+2],'receieved'))
                self.main.db.commit()
                self.main.LastSMSId =  self.main.db.cursor.lastrowid
                self.main.broadcast({"respond":"sms","from":sms.number,"text":sms.text})

            if data.find("+CREG:") != -1:
                i = find_last(parts,"+CREG")
                if i+4 < length and parts[i+4] =="OK" :
                    offset = 0
                elif i+6 <= length and parts[i+6] =="OK" :
                    offset = 0
                    lac =int(parts[i+3+offset].replace('"',''),16)
                    self.main.deviceInfo["cellIdentity"] = int(parts[i+4+offset].replace('"',''),16)
                    self.main.deviceInfo["locationAreaCode"] = {'RNC': lac >> 10, 'SB':(lac & 1023)}
                else:
                    offset = -1
                    lac =int(parts[i+3+offset].replace('"',''),16)
                    self.main.deviceInfo["cellIdentity"] = str(int(parts[i+4+offset].replace('"',''),16))
                    self.main.deviceInfo["locationAreaCode"] = {'RNC': lac >> 10, 'SB':(lac & 1023)}

                if  parts[i+2+offset] == "1" :
                    REG  = "Yes"
                    self.main.IsRegistered = True
                    self.main.deviceInfo["registrationInfo"]= ""

                elif parts[i+2+offset] == "2" :
                    self.main.IsRegistered = False
                    REG  = "Searching .... "
                    self.main.deviceInfo["registrationInfo"]= REG

                else:
                    self.main.IsRegistered = False
                    REG  = "No"
                    self.main.deviceInfo["registrationInfo"]= "not registered"


                self.main.deviceInfo["registered"] = REG

            if data.find("+SKCCSI:") != -1:
                i = find_last(parts,"+SKCCSI")

                val =""

                if parts[i+2] =="0" and i+6 < length:
                    sqlstr="UPDATE call_log set disc_cause = ? ,call_stat = ?  where call_id =? "
                    self.main.db.execute(sqlstr,(parts[i+6],parts[i+3],str(self.main.LastCallId)))
                    self.main.db.commit()

                if parts[i+3] == "2":
                    val ="Outgoing call to : "+parts[i+7]
                elif parts[i+3] == "0":
                    val ="User picked up the call "
                elif parts[i+3] == "3":
                    val ="Outgoing call to : "+parts[i+7]   +" on progress"
                    self.main.status["ongoingCall"] = 1
                    self.main.status["lastCall"] = time.strftime("%Y-%m-%d %H:%M:%S")
                elif parts[i+3] == "4":
                    val ="Incoming call from : "+parts[i+7] +" on progress"

                    if self.main.config["mt_auto_answer"]:
                        if self.main.config["mt_number"].strip() == "" or parts[i+7].strip() == self.main.config["mt_number"].strip() :
                            self.main.write("ATA" + '\r\n')

                    self.main.status["ongoingCall"] = 1

                elif parts[i+3] == "6":
                    val ="call disconnected"
                    self.main.status["ongoingCall"] = 0
                
                self.main.broadcast(self.main.deviceInfo)

            if data.find("+SKCTVI:") != -1:
                i = find_last(parts,"+SKCTVI")
                val ="Call lasted for "+parts[i+2]+"s"

                sqlstr="UPDATE call_log set dur = ? where  call_id =? "
                self.main.db.execute(sqlstr,(parts[i+2],str(self.main.LastCallId)))
                self.main.db.commit()

                self.main.broadcast({"respond":"call_info","data":val})

            if data.find("+CIMI:") != -1:
                i = find_last(parts,"+CIMI")
                IMSI = parts[i+1].replace('"','')

                if self.main.deviceInfo["IMSI"] != None and IMSI != self.main.config["IMSI"] :
                    logging.warning("IMSI changed from "+self.main.config["IMSI"]+" to "+self.main.deviceInfo["IMSI"])

                self.main.deviceInfo["IMSI"] = IMSI
                self.main.broadcast(self.main.deviceInfo)

            if data.find("+CIND:") != -1:
                i = find_last(parts,"+CIND")
                self.main.status["signalStrength"] =parts[i+1]
                self.main.status["service"] = "Ready for service" if parts[i+2]=="1" else "No service"
                self.main.status["isRoaming"] =  "Yes" if parts[i+3]=="1" else "No"
                self.main.status["isSmsFull"] =parts[i+4]

                self.main.broadcast(self.main.status)

            if data.find("+SKCNLI:") != -1:
                i = find_last(parts,"+SKCNLI")
                self.main.status["PROV1"] =parts[i+1]
                self.main.status["PROV2"] =parts[i+2]
                self.main.status["MCC"] =parts[i+3]
                self.main.status["CID"] =parts[i+5]

                self.main.broadcast(self.main.status)

            if data.find("+SKMODEL:") != -1:
                i = find_last(parts,"+SKMODEL")
                self.main.deviceInfo["model"] =parts[i+1].replace('"','')
                #self.main.broadcast(self.main.deviceInfo)

            if data.find("+SKGPSPOSI:") != -1:
                i = parts.index("+SKGPSPOSI")
                self.main.deviceInfo["gpsStatus"] == "Valid" if parts[i+1]=="1" else "Invalid"
                #self.main.broadcast(self.main.deviceInfo)

            if data.find("+CIEV:") != -1:
                i = find_last(parts,"+CIEV")
                index = int(parts[i+1])
                value = parts[i+2]
                cind = {1:"battery",2:"signalStrength",3:"service",4:"sounder",5:"smsRec",6:"callInProgress",7:"tx",8:"isRoaming",9:"isSmsFull"}
                if cind[index] =="service":
                    value = "Ready for service" if value=="1" else "No service"

                self.main.status[cind[index]]= value
                self.main.broadcast(self.main.status)

            if data.find("+SKEXTREG:") != -1:
                i = find_last(parts,"+SKEXTREG")
                index = parts[i+1]
                self.main.deviceInfo["registrationInfo"]= index

            self.main.broadcast(data)
        except Exception as e:
            logging.error(str(e))

        logging.debug(data.replace('OK','').strip())



class GSPS:

    def __init__(self):
        self.isConnected = False
        self.conn = False
        self.LastCallId = None
        self.wss = []
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
            'lastCall':None
        }
        
        self.atcgOnGoing =False
        self.lock = threading.Lock() 
        self.signal ={'ts':0,'rssi':None, 'ber':None}
        
        self.gb = 0
        self.config = {}
        self.db = sqlite3.connect('isatc.db',check_same_thread=False)
        self.get_config_from_db()

        self.connect()
        self.daemon = threading.Thread(target=self.keep_alive, args=())
        self.daemon.start()

        self.thread = ReaderThread(self)
        self.thread.start()

    def get_port(self):
        prefix = "/dev/ttyACM"
        listPort = glob.glob(prefix+'*')
        minPort = 1000
        logging.info(listPort)
        for acm in listPort:
            if acm.strip() != "":
                tx = int(acm.replace(prefix, ""))
                if tx < minPort :
                    minPort = tx
        if minPort == 1000:
            return False
        else:
            return prefix+str(minPort)

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

        return string
        
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
        self.write("ATD"+dest+";" + '\r\n')
        sql ="INSERT INTO `call_log`( `dest_num`, `call_stat`,`disc_cause`,timestamp) VALUES (?,?,?,?)"
        self.db.execute(sql,(dest,0,0,int(time.time())))
        self.db.commit()
        self.LastCallId =  self.db.cursor.lastrowid

        if timeout != False:                               
            time.sleep(timeout)
            self.write(b"ATH" + '\r\n')

    def make_sms(self,dest,content):
        sms = SmsSubmit(dest,content)
        for pdu in sms.to_pdu():
            self.write('AT+CMGS=%d\r' % pdu.length)
            time.sleep(0.1)
            self.write('%s\x1a' % pdu.pdu, "CMGS")

    def keep_alive(self):
        currentEpoch = 0
        lastEpoch = 0
        lastEpochCall = 0

        while True:
                    
            try:
                currentEpoch = int(time.time())
                '''read signal strength every 10 secs'''
                if currentEpoch - lastEpoch >= self.config["signal_read_interval"] and self.atcgOnGoing == False :
                    lastEpoch = currentEpoch
                    logging.debug("check signal level")
                    self.fetch_snr()

                ''' make a call every configurable interval '''
                
                if self.config["enable_atcg"] and  currentEpoch - lastEpochCall >= self.config["atcg_interval"]    :
                    lastEpochCall = currentEpoch
                    self.make_call(self.config["atcg_dest"])
                    self.atcgOnGoing = True
                
            except Exception as e:
                logging.error(str(e))

            time.sleep(1)



    def get_device_info(self):
        return {"error":"","data":self.deviceInfo}

    def add_sms_to_queue(self,dest,content):
        self.SMSQueue.push({'dest':dest,'content':content})

    def power_cycle(self):
        self.conn.write(b'AT+SKCKPD="E",1\r\n')

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