# Sockled Thumbnails applications

## Architecture

### Scribbled bot

After start bot reads variable `channels` from `config.py` file and register/update channels found there
Then bot forks itself for every channel in state `start`
A forked version of bot runs `ffmpeg` to read stream and extract audio from it
Forked bot split it to chunks and sent to google api

### Scribbled api

#### GET /api/transcript/<bane>

The call returns transcript of the named channel

```
[f@MBPro ~]$ curl -s http://localhost:8080/api/transcript/ktv2live | jq .
{
  "transcript": {
    "timestamp": 1582925822,
    "data": [
      "the creator of steam valve is the one of the gist of Premier gaming developers in the world and they are bringing title simultaneously to the mac and the Pea"
    ]
  },
  "name": "ktv2live",
  "result": "ok"
}
```

#### GET /api/list - list of registered channels

Response is JSON with list of registered channels

```
[f@MBPro ~]$ curl -s http://localhost:8080/api/list | jq .
[
  {
    "src": "http://qthttp.apple.com.edgesuite.net/1010qwoeiuryfg/sl.m3u8",
    "land": "ar-KW",
    "name": "ch1live",
    "pid": "34286",
    "state": "start",
    "pid_ffmpeg": "34287"
  },
  {
    "src": "http://qthttp.apple.com.edgesuite.net/1010qwoeiuryfg/sl.m3u8",
    "land": "en-US",
    "name": "ch2live",
    "pid": "0",
    "state": "stop",
    "pid_ffmpeg": "0"
  }
]
```

#### POST /api/register - register or update channel

The call accepts JSON body as a channel data

```
[f@MBPro ~]$ curl -X POST -H 'Content-Type: application/json' -d @ch3live.json -s http://localhost:8080/api/register | jq .
{
  "name": "ktv3live",
  "result": "registered"
}
```

```
[f@MBPro ~]$ cat ch3live.json
{
  "name": "ch3live",
  "lang": "en-US",
  "src": "http://qthttp.apple.com.edgesuite.net/1010qwoeiuryfg/sl.m3u8",
  "creds": "nNlcnZpY2VfYWNjb3VudCIsCiAgInByb2plY3RfaWQiOiAidm9pY2UtcmVjLTI2NjUyMiIsCiAgInByaXZhdGVfa2V5X2lkIjogIjBkODZhZjk1N2YzNGRiNTYzMGQ2M2M5ODU0OGZmOTZjNzJ3Lmdvb2dsZWFwaXMuY29tL3JvYm90L3YxL21ldGFkYXRhL3g1MDkvdXNlci0xJTQwdm9pY2UtcmVjLTI2NjUyMi5pYW0uZ3NlcnZpY2VhY2NvdW50LmNvbSIKfQo=",
  "state": "start"
}
```

Fields are:

* name - name of channel - numeric and alphabetic symbols
* lang - language of channel (https://cloud.google.com/speech-to-text/docs/languages)
* src - source of stream, can be any of supported by ffmpeg
* creds - base64 encoded of credentials json file from google
* state - state of channel, allowed values 'start' and 'stop'

#### POST /api/stop/<channel>
#### POST /api/start/<channel>

The call updates state of channel to start or stop

```
[f@MBPro ~]$ curl -X POST -s http://localhost:8080/api/stop/ktv1live | jq .
{
  "state": "stop",
  "name": "ktv1live",
  "result": "updated"
}
```

## Requirements

Python 2.7
pip
virtualenv
git
ffmpeg

#### Ubuntu

```
apt-get update && \
apt-get install -y python-dev python-pip python-virtualenv git ffmpeg
```

#### RHEL7 / CentOS7

```
yum install -y python-devel python2-pip python-virtualenv git gcc
```

### Clone-and-start

#### Clone repo and install packages

```
set -e
mkdir -p /var/lib/scribbled
cd /var/lib/scribbled
git clone --depth 1 https://github.com/freddygood/scribbled.git app
virtualenv venv
venv/bin/pip install pip==18.1 setuptools==40.4.3
venv/bin/pip install -r app/requirements.txt
```

#### Configure the application (replace example.com with real hostname)

```
cat <<EOF > /var/lib/scribbled/app/config.py

debug = True
host = '127.0.0.1'
port = 8080

sample_rate = 16000
chunk_len = 10
chunk_set_len = 3
offset_sec = 10

transcript_set_len = 1

sleep_sec = 5

work_dir = './work'
dest_dir = '/tmp/transcript_files'
db_filename = 'channels.db'

channels = [
	{
		'name': 'ktv1live',
		'lang': 'ar-KW',
		'src': 'http://qthttp.apple.com.edgesuite.net/1010qwoeiuryfg/sl.m3u8',
		'creds': 'eEdIWWx4RXZiamdvdTc3WERFN21cbmlBbUZ0R1FCQktQVG1kcW11a2FCcXdXMkhJS0...FE=',
		'state': 'start'
	},
	{
		'name': 'ktv2live',
		'lang': 'en-US',
		'src': 'http://qthttp.apple.com.edgesuite.net/1010qwoeiuryfg/sl.m3u8',
		'creds': 'eEdIWWx4RXZiamdvdTc3WERFN21cbmlBbUZ0R1FCQktQVG1kcW11a2FCcXdXMkhJS0...FE=',
		'state': 'start'
	}
]
EOF
```

### Start the applications manually

```
cd /var/lib/scribbled/app
# start bot
/var/lib/scribbled/venv/bin/python scribbled_bot.py
# start api
/var/lib/scribbled/venv/bin/uwsgi --ini uwsgi.ini
```

### Start the application

#### systemd (Ubuntu 16) / RHEL7 / CentOS7

```
cp -v app/scribbled-*.service /etc/systemd/system/
systemctl daemon-reload

systemctl enable scribbled-api.service
systemctl start scribbled-api.service

systemctl enable scribbled-bot.service
systemctl start scribbled-bot.service
```

#### upstart (Ubuntu 14)

```
cp /var/lib/scribbled/app/scribbled-bot.conf /var/lib/scribbled/app/scribbled-api.conf /etc/init/
start scribbled-api
start scribbled-bot
```

### Restart the application

#### systemd

```
systemctl restart scribbled-api.service
systemctl restart scribbled-bot.service
```

#### upstart

```
restart scribbled-api
restart scribbled-bot
```

### Configure nginx

#### upstream configuration

```
upstream scribbled {
    server 127.0.0.1:8089;
}
```


#### thumbnails location

```
location /api {
    include uwsgi_params;
    uwsgi_pass scribbled;
    client_max_body_size 1M;
}
```
