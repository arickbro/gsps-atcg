import threading
import logging
import time
from gsps_helper import *
from messaging.sms import SmsDeliver

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

                self.main.broadcast({'respond':'deviceInfo','data':self.main.deviceInfo})

            if data.find("+SKCTIME:") != -1:
                i = find_last(parts,"+SKCTIME")
                self.main.deviceInfo["gpsTimestamp"] = parts[i+1]+" "+parts[i+2]+":"+parts[i+3]+":"+parts[i+4]
                self.main.deviceInfo["gpsTimestamp"] = self.main.deviceInfo["gpsTimestamp"].replace("/","-")
                #os.system("date -s '"+info["LOC_TIME"]+"'")
                self.main.broadcast({'respond':'deviceInfo','data':self.main.deviceInfo})

            if data.find("RING") != -1:
                logging.info("ringing")
                self.main.broadcast({"respond":"ring","data":"Ringing"})

            if data.find("+CSQ:") != -1:
                i = find_last(parts,"+CSQ")

                ts = int(time.time())
                sqlstr="INSERT OR IGNORE INTO gsps_snr_ber (snr ,ber,timestamp) VALUES(?,?,?)"
                self.main.db.execute(sqlstr,(parts[i+1],parts[i+2],ts))
                self.main.db.commit()

                self.main.signal = {'ts':ts,'rssi':parts[i+1], 'ber':parts[i+2]}
                self.main.broadcast({"respond":"rssi","data":self.main.signal})
                    
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
                self.main.LastSMSId =  self.main.db.cursor().lastrowid
                self.main.broadcast({"respond":"sms","data":{"from":sms.number,"text":sms.text}})
                
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
                
                self.main.broadcast({'respond':'deviceInfo','data':self.main.deviceInfo})
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
                self.main.broadcast({'respond':'deviceInfo','data':self.main.deviceInfo})

            if data.find("+CIND:") != -1:
                i = find_last(parts,"+CIND")
                self.main.status["signalStrength"] =parts[i+1]
                self.main.status["service"] = "Ready for service" if parts[i+2]=="1" else "No service"
                self.main.status["isRoaming"] =  "Yes" if parts[i+3]=="1" else "No"
                self.main.status["isSmsFull"] =parts[i+4]

                self.main.broadcast({'respond':'deviceStatus','data':self.main.status})

            if data.find("+SKCNLI:") != -1:
                i = find_last(parts,"+SKCNLI")
                self.main.status["prov1"] =parts[i+1]
                self.main.status["prov2"] =parts[i+2]
                self.main.status["mcc"] =parts[i+3]
                self.main.status["cid"] =parts[i+5]

                self.main.broadcast({'respond':'deviceStatus','data':self.main.status})

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
                self.main.broadcast({'respond':'deviceStatus','data':self.main.status})

            if data.find("+SKEXTREG:") != -1:
                i = find_last(parts,"+SKEXTREG")
                index = parts[i+1]
                self.main.deviceInfo["registrationInfo"]= index

            self.main.broadcast({'respond':'raw','data':data.strip()})

        except Exception as e:
            logging.error(str(e))

        logging.debug(data.replace('OK','').strip())