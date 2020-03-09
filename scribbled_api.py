#!/usr/bin/env python

import os
import sys
import json
import redis
import base64

from flask import Flask, Response, request, abort

import config

application = Flask(__name__)

host = getattr(config, 'host')
port = getattr(config, 'port')
debug = getattr(config, 'debug')

redis_host = getattr(config, 'redis_host')
redis_port = getattr(config, 'redis_port')

r = redis.Redis(host=redis_host, port=redis_port, db=0)
r.ping()


@application.route('/api/list', methods=['GET'])
def get_list():
    application.logger.debug('Requested list of channels')

    response = Response()
    channels = []

    try:
        for name in r.keys('*'):

            application.logger.debug('Getting data for channel {}'.format(name))

            src = r.hget(name, 'src')
            lang = r.hget(name, 'lang')
            creds = r.hget(name, 'creds')
            state = r.hget(name, 'state')
            pid = r.hget(name, 'pid')
            pid_ffmpeg = r.hget(name, 'pid_ffmpeg')

            channels.append({
                'name': name,
                'src': src,
                'land': lang,
                'state': state,
                'pid': pid,
                'pid_ffmpeg': pid_ffmpeg
            })

        response.set_data(json.dumps(channels))
        response.mimetype = 'application/json'
        response.status_code = 200

    except Exception as e:
        application.logger.error('Unexpected exception: {0}'.format(e.message), exc_info=True)
        response.set_data(json.dumps({
            'result': 'unexpected error'
        }))
        response.status_code = 500

    return response


@application.route('/api/register/<name2>', methods=['POST'])
def register_channel(name2):
    application.logger.debug('Requested registration of channels')

    response = Response()

    if request.is_json:
        application.logger.debug('Got parameters as JSON payload')
        try:
            name = request.json['name']
            src = request.json['src']
            lang = request.json['lang']
            creds = request.json['creds']
            state = request.json['state']
        except Exception as e:
            application.logger.error('Could not parse json: {0}'.format(e.message), exc_info=True)
            response.set_data(json.dumps({
                'result': 'could not parse json'
            }))
            response.status_code = 500
            return response

    elif request.content_type == 'application/x-www-form-urlencoded':
        if len(request.form) > 0:
            application.logger.debug('Got parameters as request body')
            name = request.form.get('name')
            src = request.form.get('src')
            lang = request.form.get('lang')
            creds = request.form.get('creds')
            state = request.form.get('state')
        else:
            application.logger.debug('Got parameters as arguments')
            name = request.args.get('name')
            src = request.args.get('src')
            lang = request.args.get('lang')
            creds = request.args.get('creds')
            state = request.args.get('state')

    else:
        application.logger.error('Unsupported content type: {0}'.format(request.content_type))
        response.set_data(json.dumps({
            'result': 'unsupported content type'
        }))
        response.status_code = 400
        return response

    assert name is not None, 'Channel has no field name'
    assert src is not None, 'Channel {} has no field src'.format(name)
    assert lang is not None, 'Channel {} has no field lang'.format(name)
    assert creds is not None, 'Channel {} has no field creds'.format(name)
    assert state is not None, 'Channel {} has no field state'.format(name)

    assert name == name2, 'Channel name from URI differs from payload'
    assert '|' not in name, 'Channel name cannot have pipe symbol (|)'
    assert state in ['start', 'stop'], 'Channel {} state must be one of [start, stop] but found {}'.format(name, state)

    try:
        if r.exists(name):
            application.logger.debug('Updating data for channel {}'.format(name))
            result = 'updated'
        else:
            application.logger.debug('Registering channel {}'.format(name))
            result = 'registered'

        with r.pipeline() as pipe:
            pipe.multi()
            pipe.hset(name, 'src', src)
            pipe.hset(name, 'lang', lang)
            pipe.hset(name, 'creds', creds)
            pipe.hset(name, 'state', state)
            pipe.execute()

        response.set_data(json.dumps({
            'name': name,
            'result': result
        }))
        response.mimetype = 'application/json'
        response.status_code = 200

    except Exception as e:
        application.logger.error('Unexpected exception: {0}'.format(e.message), exc_info=True)
        response.set_data(json.dumps({
            'result': 'unexpected error'
        }))
        response.status_code = 500

    return response


@application.route('/api/start/<name>', methods=['POST'])
@application.route('/api/stop/<name>', methods=['POST'])
def update_channel(name):

    state = 'start' if str(request.url_rule).startswith('/api/start/') else 'stop'

    application.logger.debug('Requested change state of channel {} to {}'.format(name, state))

    response = Response()

    try:
        if r.exists(name):
            if r.hget(name, 'state') == state:
                application.logger.debug('State of channel {} remains unchanged'.format(name))
                result = 'unchanged'

            else:
                application.logger.debug('State of channel {} updated to {}'.format(name, state))
                r.hset(name, 'state', state)
                result = 'updated'

            response.set_data(json.dumps({
                'name': name,
                'state': state,
                'result': result
            }))
            response.mimetype = 'application/json'
            response.status_code = 200

        else:
            application.logger.warn('Channel {} not registered'.format(name))
            response.set_data(json.dumps({
                'name': name,
                'result': 'channel not found'
            }))
            response.status_code = 404

    except Exception as e:
        application.logger.error('Unexpected exception: {0}'.format(e.message), exc_info=True)
        response.set_data(json.dumps({
            'name': name,
            'state': state,
            'result': 'unexpected error'
        }))
        response.status_code = 500

    return response


@application.route('/api/purge/<name>', methods=['POST'])
def purge_channel(name):
    application.logger.debug('Requested purging of channel {}'.format(name))

    response = Response()

    try:
        if r.exists(name):
            if r.hexists(name, 'transcript'):
                application.logger.debug('Purging of transcript of channel {}'.format(name))
                r.hdel (name, 'transcript')
                result = 'deleted'

            else:
                application.logger.debug('Channel {} has no transcript'.format(name))
                result = 'unchanged'

            response.set_data(json.dumps({
                'name': name,
                'result': result
            }))
            response.mimetype = 'application/json'
            response.status_code = 200

        else:
            application.logger.warn('Channel {} not registered'.format(name))
            response.set_data(json.dumps({
                'name': name,
                'result': 'channel not found'
            }))
            response.status_code = 404

    except Exception as e:
        application.logger.error('Unexpected exception: {0}'.format(e.message), exc_info=True)
        response.set_data(json.dumps({
            'name': name,
            'result': 'unexpected error'
        }))
        response.status_code = 500

    return response


@application.route('/api/remove/<name>', methods=['POST'])
def remove_channel(name):
    application.logger.debug('Requested removing of channel {}'.format(name))

    response = Response()

    try:
        if r.exists(name):
            application.logger.debug('Removing of channel {}'.format(name))
            r.delete(name)
            response.set_data(json.dumps({
                'name': name,
                'result': 'removed'
            }))
            response.mimetype = 'application/json'
            response.status_code = 200

        else:
            application.logger.warn('Channel {} not registered'.format(name))
            response.set_data(json.dumps({
                'name': name,
                'result': 'channel not found'
            }))
            response.status_code = 404

    except Exception as e:
        application.logger.error('Unexpected exception: {0}'.format(e.message), exc_info=True)
        response.set_data(json.dumps({
            'name': name,
            'result': 'unexpected error'
        }))
        response.status_code = 500

    return response


@application.route('/api/transcript/<name>', methods=['GET'])
def get_transcript(name):
    set = request.args.get('set')
    if set is not None and set.isdigit():
        set_int = int(set)
        application.logger.debug('Requested set of {} transcript of channel {}'.format(set, name))
    else:
        set_int = 0
        application.logger.debug('Requested transcript of channel {}'.format(name))

    response = Response()

    try:
        if r.exists(name):
            if r.hexists(name, 'transcript'):
                application.logger.debug('Getting transcript of channel {}'.format(name))
                transcript = json.loads(r.hget(name, 'transcript'))
                if set_int:
                    response.set_data(json.dumps({
                        'name': name,
                        'transcript': transcript[0-set_int:],
                        'result': 'ok',
                        'set': len(transcript[0-set_int:]),
                        'full_set': len(transcript)
                    }))
                else:
                    response.set_data(json.dumps({
                        'name': name,
                        'transcript': transcript,
                        'result': 'ok',
                        'full_set': len(transcript)
                    }))
                response.mimetype = 'application/json'
                response.status_code = 200

            else:
                application.logger.warn('Transcript of channel {} not found'.format(name))
                response.set_data(json.dumps({
                    'name': name,
                    'result': 'transcript not found'
                }))
                response.mimetype = 'application/json'
                response.status_code = 404

        else:
            application.logger.warn('Channel {} not registered'.format(name))
            response.set_data(json.dumps({
                'name': name,
                'result': 'channel not registered'
            }))
            response.status_code = 404

    except Exception as e:
        application.logger.error('Unexpected exception: {0}'.format(e.message), exc_info=True)
        response.set_data(json.dumps({
            'name': name,
            'result': 'unexpected error'
        }))
        response.status_code = 500

    return response


if __name__ == '__main__':
    application.run(
        debug = debug,
        host = host,
        port = port
    )
