#!/usr/bin/env python

import os
import sys
import json
import time
import redis
import base64
import logging

import subprocess
from multiprocessing import Process

from google.cloud import speech
from google.cloud.speech import enums
from google.cloud.speech import types

import config

channels = getattr(config, 'channels')

sample_rate = getattr(config, 'sample_rate')
chunk_sec = getattr(config, 'chunk_sec')
chunk_set_len = getattr(config, 'chunk_set_len')
offset_sec = getattr(config, 'offset_sec')
transcript_set_len = getattr(config, 'transcript_set_len')
sleep_sec = getattr(config, 'sleep_sec')

chunk_bytes = int(sample_rate * chunk_sec)

work_dir = getattr(config, 'work_dir')

redis_host = getattr(config, 'redis_host')
redis_port = getattr(config, 'redis_port')

r = redis.Redis(host=redis_host, port=redis_port, db=0)
r.ping()

logger = logging.getLogger(__name__)
logging.basicConfig(
    level = logging.DEBUG,
    format = '%(asctime)s - %(levelname)s - %(message)s'
)


def update_pid(name, pid = 0):
    logger.debug('Updating pid for channel {} to {}'.format(name, pid))
    r.hset(name, 'pid', pid)

def update_pid_ffmpeg(name, pid = 0):
    logger.debug('Updating ffmpeg pid for channel {} to {}'.format(name, pid))
    r.hset(name, 'pid_ffmpeg', pid)


def dummy_loop(name, src, lang, creds):
    def ffmpeg_process(source):
        logger.debug('Starting ffmpeg process {}'.format(source))
        args = [
            'ffmpeg',
            '-re',
            '-itsoffset', '-' + str(offset_sec),
            '-i', source,
            '-f', 's16le',
            '-ac', '1',
            '-acodec', 'pcm_s16le',
            '-ar', str(sample_rate),
            'pipe:'
        ]
        logger.debug('ffmpeg string: {}'.format(args))
        return subprocess.Popen(args, stdout=subprocess.PIPE)

    process = ffmpeg_process(src)

    update_pid_ffmpeg(name, process.pid)

    i = 0
    while True:
        # logger.debug('Process channel {} status = {}'.format(name, process.poll()))
        # logger.debug('Process channel {} pid = {}'.format(name, process.pid))

        i += 1
        logger.debug('Channel {} reading chunk {}'.format(name, i))
        if i == 100:
            logger.warn('End of stream channel {}'.format(name))
            break
        time.sleep(1)

    logger.error('Terminating channel {}'.format(name))
    if process.poll() is None:
        process.kill()
    process.wait()

    update_pid_ffmpeg(name)

    time.sleep(sleep_sec)

def channel_loop(name, src, lang, creds):
    def ffmpeg_process(source):
        logger.debug('Starting ffmpeg process {}'.format(source))
        args = [
            'ffmpeg',
            '-re',
            '-itsoffset', '-' + str(offset_sec),
            '-i', source,
            '-f', 's16le',
            '-ac', '1',
            '-acodec', 'pcm_s16le',
            '-ar', str(sample_rate),
            'pipe:'
        ]
        logger.debug('ffmpeg string: {}'.format(args))
        return subprocess.Popen(args, stdout=subprocess.PIPE)

    def transcript_chunk(data, lang):
        logger.debug('Transcription of incoming set of {} chunks'.format(len(data)))

        requests = (types.StreamingRecognizeRequest(audio_content = chunk)
            for chunk in data)

        responses = client.streaming_recognize(streaming_config, requests)

        transcript = []

        for response in responses:
            for result in response.results:
                transcript.append(result.alternatives[0].transcript)

        return transcript


    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds

    client = speech.SpeechClient()
    config = types.RecognitionConfig(
        encoding = enums.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz = int(sample_rate),
        language_code = lang,
        max_alternatives = 1
    )
    streaming_config = types.StreamingRecognitionConfig(
        config = config
        # config = config,
        # interim_results = True
    )

    chunk_set = []
    if r.hexists(name, 'transcript'):
        logger.debug('Loading transcript of channel {} into current set'.format(name))
        transcript_set = json.loads(r.hget(name, 'transcript'))
    else:
        transcript_set = []

    process = ffmpeg_process(src)

    update_pid_ffmpeg(name, process.pid)

    while True:

        chunk = process.stdout.read(chunk_bytes)
        if not chunk:
            logger.warn('End of stream {}'.format(name))
            break

        logger.debug('Reading chunk of {} bytes'.format(len(chunk)))
        chunk_set.append(chunk)

        while len(chunk_set) > chunk_set_len:
            logger.debug('Chunk set length {} larger then limit {}, popping oldest item'.format(
                len(chunk_set), chunk_set_len)
            )
            chunk_set.pop(0)

        logger.debug('Transcription current set of {} chunks'.format(len(chunk_set)))
        transcript = transcript_chunk(chunk_set, lang)

        timestamp = int(time.time())

        if len(transcript):
            logger.debug('Updating channel {} transcription'.format(name))
            transcript_set.append({
                timestamp: transcript
            })
            # transcript_set.append({
            #     'timestamp': timestamp,
            #     'data': transcript
            # })

            while len(transcript_set) > transcript_set_len:
                logger.debug('Transcript set length {} larger then limit {}, popping oldest item'.format(
                    len(transcript_set), transcript_set_len)
                )
                transcript_set.pop(0)

            r.hset(name, 'transcript', json.dumps(transcript_set))


    logger.error('Terminating channel {}'.format(name))
    if process.poll() is None:
        process.kill()
    process.wait()

    update_pid_ffmpeg(name)

    time.sleep(sleep_sec)


def create_dir_first():
    if not os.path.exists(work_dir):
        os.makedirs(work_dir)


def register_channels_first():
    for channel in channels:
        assert channel['name'] is not None, 'Channel has no field name'
        assert channel['src'] is not None, 'Channel {} has no field src'.format(channel['name'])
        assert channel['lang'] is not None, 'Channel {} has no field lang'.format(channel['name'])
        assert channel['creds'] is not None, 'Channel {} has no field creds'.format(channel['name'])
        assert channel['state'] is not None, 'Channel {} has no field state'.format(channel['name'])

        assert '|' not in channel['name'], 'Channel name cannot have pipe symbol (|)'
        assert channel['state'] in ['start', 'stop'], 'Channel {} state must be one of [start, stop] but found {}'.format(channel['name'], channel['state'])

    for channel in channels:
        name = channel['name']
        logger.info('Storing data for channel {}'.format(name))
        with r.pipeline() as pipe:
            pipe.multi()
            pipe.hset(name, 'src', channel['src'])
            pipe.hset(name, 'lang', channel['lang'])
            pipe.hset(name, 'creds', channel['creds'])
            pipe.hset(name, 'state', channel['state'])
            pipe.execute()


def reset_pids_first():
    for name in r.keys('*'):
        logger.info('Resetting pids for channel {}'.format(name))
        with r.pipeline() as pipe:
            pipe.multi()
            pipe.hset(name, 'pid', 0)
            pipe.hset(name, 'pid_ffmpeg', 0)
            pipe.execute()


def reset_transcripts_first():
    for name in r.keys('*'):
        logger.info('Resetting transcript for channel {}'.format(name))
        r.hdel (name, 'transcript')


def run_channels():

    def control_channel(name, src, lang, creds, state):

        global processes

        if state == 'start':
            if name not in processes.keys() or not processes[name].is_alive():
                logger.debug('Registering process for channel {}'.format(name))
                creds_filename = os.path.join(work_dir, name + '-creds.json')

                logger.debug('Saving credentials for channel {} to file {}'.format(name, creds_filename))
                f = open(creds_filename, 'w' )
                f.write(base64.b64decode(creds))
                f.close()

                logger.info('Starting process for channel {}'.format(name))
                processes[name] = Process(
                    target = channel_loop,
                    name = 'channel_loop_{}'.format(name),
                    args = (name, src, lang, creds_filename)
                )

                processes[name].start()
                update_pid(name, processes[name].pid)

        if state == 'stop':
            if name in processes.keys():
                if processes[name].is_alive():
                    logger.info('Stopping process for channel {}'.format(name))
                    processes[name].terminate()

                update_pid(name)
                update_pid_ffmpeg(name)

                logger.debug('Unregistering process for channel {}'.format(name))
                del processes[name]

    global processes

    for name in r.keys('*'):
        logger.debug('Control iteration for channel {}'.format(name))

        src = r.hget(name, 'src')
        lang = r.hget(name, 'lang')
        creds = r.hget(name, 'creds')
        state = r.hget(name, 'state')

        control_channel(name, src, lang, creds, state)


if __name__ == '__main__':
    create_dir_first()
    register_channels_first()
    reset_pids_first()

    processes = {}

    while True:
        run_channels()
        time.sleep(sleep_sec)
