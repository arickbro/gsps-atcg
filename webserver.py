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
    ic.add_to(sock)
    while True:
        data = sock.receive()
        print(data)
        time.sleep(0.1)

@app.route('/status', methods=['GET'])
def get_status():
    response = app.response_class(
        response=json.dumps(ic.get_status()),
        status=200,
        mimetype='application/json'
    )
    return response
@app.route('/configuration', methods=['GET'])
def get_config_from_db():
    response = app.response_class(
        response=json.dumps(ic.get_config_from_db()),
        status=200,
        mimetype='application/json'
    )
    return response

@app.route('/info', methods=['GET'])
def get_info():
    response = app.response_class(
        response=json.dumps(ic.get_device_info()),
        status=200,
        mimetype='application/json'
    )
    return response

@app.route('/snr', methods=['GET'])
def last():
    response = app.response_class(
        response=json.dumps(ic.get_snr()),
        status=200,
        mimetype='application/json'
    )
    return response

@app.route('/historical_snr', methods=['GET'])
def get_historical_snr():
    parameter = {}
    parameter['start'] = request.form.get('start')
    parameter['end'] = request.form.get('end')
    parameter['bucket'] = request.form.get('bucket')
    return json.dumps(ic.get_historical_snr(parameter))

@app.route('/smses', methods=['GET'])
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
        result =  ic.write(bytes(cmd+"\r\n", 'utf-8'),b"OK")
    except Exception as e:
        result["error"] = str(e)

    return result

@app.route('/call', methods=['POST'])
def send_call():
    result = {"error":"","data":{}}
    try:
        dest = request.form.get('dest')
        timeout = int(request.form.get('duration'))
        result['data'] = ic.make_call(dest,timeout)
    except Exception as e:
        result["error"] = str(e)
    return result

@app.route('/hangup', methods=['GET'])
def hangup():
    result = {"error":"","data":{}}
    try:
        result =  ic.write(bytes("ATH\r\n", 'utf-8'),b"OK")
    except Exception as e:
        result["error"] = str(e)
    return result


@app.route('/reboot_terminal', methods=['GET'])
def power_cycle():
    result = {"error":"","data":{}}
    try:
        result['data'] = ic.power_cycle()
    except Exception as e:
        result["error"] = str(e)
    return result


@app.route('/sms', methods=['POST'])
def send_sms():
    result = {"error":"","data":{}}
    try:
        dest = request.form.get('dest')
        content = request.form.get('content')
        result['data'] = ic.make_sms(dest,content)
    except Exception as e:
        result["error"] = str(e)
    return result


@app.route('/configuration', methods=['POST'])
def set_config():
    return json.dumps(ic.set_config(request.json))

if __name__ == '__main__':
    app.run()