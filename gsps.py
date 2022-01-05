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

class GSPS:
    def __init__(self):
        self.isConnected = False
        self.conn = False
        self.LastCallId = None
        self.wss = []
        self.SMSQueue = []
        self.deviceInfo = {}
        self.status = {}
        self.atcgOnGoing =False
        self.lock = threading.Lock() 
        self.signal ={'ts':0,'signal':None}
        
        self.config = {}
        self.db = sqlite3.connect('isatc.db',check_same_thread=False)
        self.get_config_from_db()

        self.connect()
        self.daemon = threading.Thread(target=self.keep_alive, args=())
        self.daemon.start()

        self.serialReader = threading.Thread(target=self.read_from_port, args=())
        self.serialReader.start()

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
                    result['data'][row[0]] = int(row[1])
                elif row[2] == "bytes":
                    result['data'][row[0]] = bytes(row[1], 'utf-8')
                else:
                    result['data'][row[0]]  = None if row[1].strip() == '' else row[1].strip()

        except Exception as e:
            result["error"] = str(e)

        self.config = result['data']
        print(self.config)
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
            sql = "select (timestamp/?)*? as ts, avg(signal_level), sum(ber) as snr from gsps_signal where timestamp >= ? and timestamp < ? group by ts "
            cursor = self.db.execute(sql, (param['bucket'],param['bucket'],param['start'],param['end']))
            for row in cursor:
                result["data"].append(row)
        except Exception as e:
            result["error"] = str(e)
        return result
    def get_calls(self,param):

        result = {"error":"","columns":["les","service","priority","lang","timestamp","bytes","sequence","error","repetition","filename"], "rows":[],"count":None}
        sql = "select count(timestamp) from isatc_egc where timestamp >= ? and timestamp < ? "
        try:
            cursor = self.db.execute(sql, (param['start'],param['end']))
            result["output"] = cursor.fetchone()[0]
            
            sql = "select "+",".join(result["columns"])+" from gsps_calls where timestamp >= ? and timestamp < ?  LIMIT ? OFFSET ?"
            cursor = self.db.execute(sql, (param['start'],param['end'],param['limit'],param['offset']))
            for row in cursor:
                result["data"].append(row)
        except Exception as e:
            result["error"] = str(e)
        return result

    def get_sms(self,param):

        result = {"error":"","columns":["filename","timestamp","bytes","content"], "rows":[],"count":None}
        sql = "select count(timestamp) from isatc_dir where timestamp >= ? and timestamp < ? "
        try:
            cursor = self.db.execute(sql, (param['start'],param['end']))
            result["output"] = cursor.fetchone()[0]
            
            sql = "select "+",".join(result["columns"])+" from gsps_sms where timestamp >= ? and timestamp < ?  LIMIT ? OFFSET ?"
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

    def read_from_port(self):
        try:
            if self.conn.isOpen() :
                while True:
                    tdata = self.conn.read().decode('ascii')
                    time.sleep(0.2)
                    if self.conn.inWaiting() > 0:
                        tdata += self.conn.read(self.conn.inWaiting()).decode('ascii')

                    if tdata.strip() != "":
                        self.parsing_serial(tdata)

        except Exception as e:
            ErrorString = str(e)
            logging.error(ErrorString)
            if ErrorString.find("device reports readiness to read but returned no data") != -1 or ErrorString.find("I/O error") != -1  :
                logging.info("exiting")
                time.sleep(5)

    def write(self,data,expect=False):
        string =""
        self.lock.acquire() 
        #logging.debug("lock:"+str(time.time()))
        
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
        #logging.debug("release:"+str(time.time()))
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
        sql ="INSERT INTO `call_log`( `dest_num`, `call_stat`,`disc_cause`,ts) VALUES (?,?,?,?)"
        self.db.execute(sql,(dest,0,0,int(time.time())))
        self.db.commit()
        self.LastCallId =  self.db.cursor.lastrowid

        if timeout != False:                               
            time.sleep(timeout)
            self.write("ATH" + '\r\n')

    def make_sms(self,dest,content):
        sms = SmsSubmit(dest,content)
        for pdu in sms.to_pdu():
            self.write('AT+CMGS=%d\r' % pdu.length)
            time.sleep(0.1)
            self.write('%s\x1a' % pdu.pdu, "CMGS")

    def keep_alive(self):
        currentEpoch = 0
        lastEpoch = 0
        lastEpochEgc = 0
        lastEpochEmail = 0

        while True:
      
            if self.isConnected == False:
                logging.debug("not connected ")
                time.sleep(5)
                self.connect()
                continue
                
            try:
                currentEpoch = int(time.time())
                '''read signal strength every 10 secs'''
                if currentEpoch - lastEpoch >= self.config["signal_read_interval"] and self.atcgOnGoing == False :
                    lastEpoch = currentEpoch
                    logging.debug("check signal level")
                    self.fetch_snr()
                    #if ( self.signal['signal'] != None and self.signal['signal'] > 0):
                        #self.fetch_info()

                ''' make a call every configurable interval '''
                
                if self.config["enable_atcg"] and  currentEpoch - lastEpochEgc >= self.config["atcg_interval"]    :
                    lastEpochEgc = currentEpoch
                    self.make_call(self.config["atcg_dest"])
                    self.atcgOnGoing = True
                
            except Exception as e:
                logging.error(str(e))

            time.sleep(1)


    def parsing_serial(self,data):
        try:
            data = str(data)
            parts =  re.split(",|:|\r\n|\r",data.strip())
            parts = list(map(str.strip,parts))
            length = len(parts)
            print(parts)

            MatchImei = re.match( r"^(353\d{12})\s+OK", data.strip(),re.MULTILINE)
            if MatchImei:
                self.deviceInfo["IMEI"] = MatchImei.group(1)

            if data.find("+SKRGPSPOS:") != -1:
                i = find_last(parts,"+SKRGPSPOS")
                if parts[i+1]=="1":
                    self.deviceInfo["LOC_STATUS"] = "Valid"
                else:
                    self.deviceInfo["LOC_STATUS"] = "Invalid"

                self.deviceInfo["LOC_LAT"] = parts[i+2]
                self.deviceInfo["LOC_LON"] = parts[i+3]
                self.deviceInfo["LOC_ALT"] = parts[i+4]
                self.deviceInfo["LOC_TIME"] = parts[i+5]+" "+parts[i+6]+":"+parts[i+7]+":"+parts[i+8]
                self.deviceInfo["LOC_TIME"] = self.deviceInfo["LOC_TIME"].replace("/","-")

                self.broadcast(self.deviceInfo)

            if data.find("+SKCTIME:") != -1:
                i = find_last(parts,"+SKCTIME")
                self.deviceInfo["LOC_TIME"] = parts[i+1]+" "+parts[i+2]+":"+parts[i+3]+":"+parts[i+4]
                self.deviceInfo["LOC_TIME"] = self.deviceInfo["LOC_TIME"].replace("/","-")
                #os.system("date -s '"+info["LOC_TIME"]+"'")
                self.broadcast(self.deviceInfo)

            if data.find("RING") != -1:
                logging.info("ringing")
                self.broadcast({"respond":"ring","data":"Ringing"})

            if data.find("+CSQ:") != -1:
                i = find_last(parts,"+CSQ")

                ts = int(time.time())
                sqlstr="INSERT INTO gsps_snr_ber (snr ,ber,timestamp) VALUES( ?,?,?)"
                self.db.execute(sqlstr,(parts[i+1],parts[i+2],ts))
                self.db.commit()

                csq ={"respond":"csq","rssi":parts[i+1], "ber":parts[i+2]}
                self.broadcast(csq)
                    
            if data.find("+CMGS:") != -1:
                self.WaitingForCMGS = False
                i = find_last(parts,"+CMGS")
                logging.info("SMS:"+parts[i+1]+" LENGTH:"+parts[i+2])

                sqlstr="UPDATE sms set status = 'sent' where SMS_ID=?"
                self.db.execute(sqlstr,(self.InsertId,))
                self.db.commit()

                self.broadcast({"respond":"call_info","data":"SMS Sent"})

            if data.find("+CMT:") != -1:
                i = find_last(parts,"+CMT")
                sms = SmsDeliver(parts[i+3])

                sql = "INSERT INTO sms (TYPE, BNUM, CONTENT,LENGTH,status) VALUES (?,?,?,?,?)"
                self.db.execute(sql, (0,sms.number,sms.text,parts[i+2],'receieved'))
                self.db.commit()
                self.broadcast({"respond":"sms","from":sms.number,"text":sms.text})

            if data.find("+CREG:") != -1:
                i = find_last(parts,"+CREG")
                if i+4 < length and parts[i+4] =="OK" :
                    offset = 0
                elif i+6 <= length and parts[i+6] =="OK" :
                    offset = 0
                    lac =int(parts[i+3+offset].replace('"',''),16)
                    self.deviceInfo["CI"] = "LRFCN:"+ str(int(parts[i+4+offset].replace('"',''),16))
                    self.deviceInfo["LAC"] = "RNC:"+str(lac >> 10)+" , SB:"+str(lac & 1023)
                else:
                    offset = -1
                    lac =int(parts[i+3+offset].replace('"',''),16)
                    self.deviceInfo["CI"] = "LRFCN:"+ str(int(parts[i+4+offset].replace('"',''),16))
                    self.deviceInfo["LAC"] = "RNC:"+str(lac >> 10)+" , SB:"+str(lac & 1023)

                if  parts[i+2+offset] == "1" :
                    REG  = "Yes"
                    self.IsRegistered = True
                    self.deviceInfo["additional"]= ""

                elif parts[i+2+offset] == "2" :
                    self.IsRegistered = False
                    REG  = "Searching .... "
                    self.deviceInfo["additional"]= REG

                else:
                    self.IsRegistered = False
                    REG  = "No"
                    self.deviceInfo["additional"]= "not registered"


                self.deviceInfo["REG"] = REG

            if data.find("+SKCCSI:") != -1:
                i = find_last(parts,"+SKCCSI")

                val =""

                if parts[i+2] =="0" and i+6 < length:
                    sqlstr="UPDATE call_log set disc_cause = ? ,call_stat = ?  where call_id =? "
                    self.db.execute(sqlstr,(parts[i+6],parts[i+3],str(self.LastCallId)))
                    self.db.commit()

                if parts[i+3] == "2":
                    val ="Outgoing call to : "+parts[i+7]
                elif parts[i+3] == "0":
                    val ="User picked up the call "
                elif parts[i+3] == "3":
                    val ="Outgoing call to : "+parts[i+7]   +" on progress"
                    self.status["ONG"] = 1
                    self.status["LAST_CALL"] = time.strftime("%Y-%m-%d %H:%M:%S")
                elif parts[i+3] == "4":
                    val ="Incoming call from : "+parts[i+7] +" on progress"

                    if self.config["mt_auto_answer"]:
                        if self.config["mt_number"].strip() == "" or parts[i+7].strip() == self.config["mt_number"].strip() :
                            self.write("ATA" + '\r\n')

                    self.status["ONG"] = 1

                elif parts[i+3] == "6":
                    val ="call disconnected"
                    self.status["ONG"] = 0
                
                self.broadcast(self.deviceInfo)

            if data.find("+SKCTVI:") != -1:
                i = find_last(parts,"+SKCTVI")
                val ="Call lasted for "+parts[i+2]+"s"

                sqlstr="UPDATE call_log set dur = ? where  call_id =? "
                self.db.execute(sqlstr,(parts[i+2],str(self.LastCallId)))
                self.db.commit()

                self.broadcast({"respond":"call_info","data":val})

            if data.find("+CIMI:") != -1:
                i = find_last(parts,"+CIMI")
                self.deviceInfo["IMSI"] = parts[i+1].replace('"','')

                #sql="REPLACE INTO site_meta (type ,value) VALUES( 'IMSI', ?)"
                #self.db.execute(sql,(self.deviceInfo["IMSI"],))
                #self.db.commit()

                #if self.deviceInfo["IMSI"] != self.config["IMSI"] :
                    #logging.warning("IMSI changed from "+self.config["IMSI"]+" to "+self.deviceInfo["IMSI"])

                self.broadcast(self.deviceInfo)

            if data.find("+CIND:") != -1:
                i = find_last(parts,"+CIND")
                self.status["SIG"] =parts[i+1]
                self.status["SERVICE"] = "Ready for service" if parts[i+2]=="1" else "No service"
                self.status["ROAM"] =  "Yes" if parts[i+3]=="1" else "No"
                self.status["SMS_FULL"] =parts[i+4]

                self.broadcast(self.status)

            if data.find("+SKCNLI:") != -1:
                i = find_last(parts,"+SKCNLI")
                self.status["PROV1"] =parts[i+1]
                self.status["PROV2"] =parts[i+2]
                self.status["MCC"] =parts[i+3]
                self.status["CID"] =parts[i+5]

                self.broadcast(self.status)

            if data.find("+SKMODEL:") != -1:
                i = find_last(parts,"+SKMODEL")
                self.deviceInfo["MODEL"] =parts[i+1].replace('"','')
                #self.broadcast(self.deviceInfo)

            if data.find("+SKGPSPOSI:") != -1:
                i = parts.index("+SKGPSPOSI")
                self.status["LOC_STATUS"] == "Valid" if parts[i+1]=="1" else "Invalid"
                self.broadcast(self.status)

            if data.find("+CIEV:") != -1:
                i = find_last(parts,"+CIEV")
                index = int(parts[i+1])
                value = parts[i+2]
                cind = {1:"BAT",2:"SIG",3:"SERVICE",4:"SOUNDER",5:"SMS_REC",6:"CALL_IN_PROGRESS",7:"TX",8:"ROAM",9:"SMS_FULL"}
                if cind[index] =="SERVICE":
                    value = "Ready for service" if value=="1" else "No service"

                self.status[cind[index]]= value
                self.broadcast(self.status)

            if data.find("+SKEXTREG:") != -1:
                i = find_last(parts,"+SKEXTREG")
                index = parts[i+1]
                self.status["additional"]= index
                self.broadcast(self.status)

        except Exception as e:
            logging.error(str(e))

        #logging.debug(data.replace('OK','').strip())
        #print info

    def get_device_info(self):
        return {"error":"","data":self.deviceInfo}

    def add_sms_to_queue(self,dest,content):
        self.SMSQueue.push({'dest':dest,'content':content})

    def power_cycle(self):
        self.conn.write('AT+SKCKPD="E",1' + '\r\n')

    def hangup(self):
        self.conn.write("ATH" + '\r\n')
    
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

ic = GSPS()
