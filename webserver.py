from flask import Flask, render_template,request
from flask_sock import Sock
import time
import json
from gsps import GSPS

app = Flask(__name__)
sock = Sock(app)
wss = []


ic = GSPS()

@sock.route('/echo', methods=['GET'])
def echo(sock):
    print(request.args.get('start'))
    sock.send("welcome")
    ic.add_to(sock)
    while True:
        data = sock.receive()
        print(data)
        time.sleep(0.1)

@app.route('/status', methods=['GET'])
def get_status():
    return json.dumps(ic.get_status())

@app.route('/configuration', methods=['GET'])
def get_config_from_db():
    return json.dumps(ic.get_config_from_db())

@app.route('/info', methods=['GET'])
def get_info():
    return json.dumps(ic.get_device_info())

@app.route('/snr', methods=['GET'])
def last():
    return json.dumps(ic.get_snr())

@app.route('/historical_snr', methods=['GET'])
def get_historical_snr():
    parameter = {}
    parameter['start'] = request.form.get('start')
    parameter['end'] = request.form.get('end')
    parameter['bucket'] = request.form.get('bucket')
    return json.dumps(ic.get_historical_snr(parameter))

@app.route('/smss', methods=['GET'])
def get_sms():
    parameter = {}
    parameter['start'] = request.form.get('start')
    parameter['end'] = request.form.get('end')
    parameter['offset'] = request.form.get('offset')
    parameter['limit'] = request.form.get('limit')
    return json.dumps(ic.get_sms(parameter))

@app.route('/calls', methods=['GET'])
def get_calls():
    parameter = {}
    parameter['start'] = request.form.get('start')
    parameter['end'] = request.form.get('end')
    parameter['offset'] = request.form.get('offset')
    parameter['limit'] = request.form.get('limit')
    return json.dumps(ic.get_calls(parameter))

@app.route('/command', methods=['POST'])
def exec():
    result = {"error":"","data":{}}
    try:
        cmd = request.form.get('cmd')
        result['data'] = ic.write(bytes(cmd+"\n", 'utf-8'))
    except Exception as e:
        result["error"] = str(e)

    return result

@app.route('/call', methods=['POST'])
def send_call():
    string = ic.make_call(request.json)
    return string

@app.route('/sms', methods=['POST'])
def send_sms():
    string = ic.make_sms(request.json)
    return string

@app.route('/configuration', methods=['POST'])
def set_config():
    return json.dumps(ic.set_config(request.json))

if __name__ == '__main__':
    app.run()