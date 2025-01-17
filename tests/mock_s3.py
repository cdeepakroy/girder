#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright 2014 Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import argparse
import boto
import errno
import logging
import os
import socket
import threading
import time

import moto.server
import moto.s3
from girder.utility.s3_assetstore_adapter import makeBotoConnectParams, \
    botoConnectS3, S3AssetstoreAdapter
from six.moves import range

_startPort = 31100
_maxTries = 100


def createBucket(botoConnect, bucketName):
    """
    Create a bucket if it doesn't already exist.
    :param botoConnect: connection parameters to pass to use with boto.
    :type botoConnect: dict
    :param bucketName: the bucket name
    :type bucket: str
    :returns: a boto bucket.
    """
    conn = botoConnectS3(botoConnect)
    bucket = conn.lookup(bucket_name=bucketName, validate=True)
    # if found, return
    if bucket is not None:
        return
    bucket = conn.create_bucket(bucketName)
    # I would have preferred to set the CORS for the bucket we created, but
    # moto doesn't support that.
    # setBucketCors(bucket)
    return bucket


def setBucketCors(bucket):
    """
    Set the cors access values on a boto bucket to allow general access to that
    bucket.
    :param bucket: a boto bucket to set.
    """
    cors = boto.s3.cors.CORSConfiguration()
    cors.add_rule(
        id='girder_cors_rule',
        allowed_method=['HEAD', 'GET', 'PUT', 'POST', 'DELETE'],
        allowed_origin=['*'],
        allowed_header=['Content-Disposition', 'Content-Type',
                        'x-amz-meta-authorized-length', 'x-amz-acl',
                        'x-amz-meta-uploader-ip', 'x-amz-meta-uploader-id'],
        expose_header=['ETag'],
        max_age_seconds=3000
        )
    bucket.set_cors(cors)


def startMockS3Server():
    """
    Start a server using the defaults and adding a configuration parameter to
    the system so that the s3 assetstore handler will know to use this
    server.  Attempt to bind to any port within the range specified by
    _startPort and _maxTries.  Bias it with the pid of the current process so
    as to reduce potential conflicts with parallel tests that are started
    nearly simultaneously.

    :returns: the started server.
    """
    # Reduce the chunk size to allow faster testing.
    S3AssetstoreAdapter.CHUNK_LEN = 1024 * 256
    moto.s3.models.UPLOAD_PART_MIN_SIZE = 1024 * 256
    # turn off logging from the S3 server unless we've asked to keep it
    if 'mocks3' not in os.environ.get('EXTRADEBUG', '').split():
        logging.getLogger('werkzeug').setLevel(logging.CRITICAL)
    selectedPort = None
    for porttry in range(_maxTries):
        port = _startPort + ((porttry + os.getpid()) % _maxTries)
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.bind(('0.0.0.0', port))
            selectedPort = port
        except socket.error as err:
            # Allow address in use errors to fail quietly
            if err.errno != errno.EADDRINUSE:
                raise
        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        test_socket.close()
        if selectedPort is not None:
            break
    server = MockS3Server(selectedPort)
    server.start()
    # add a bucket named 'bucketname' to simplify testing
    createBucket(server.botoConnect, 'bucketname')
    return server


class MockS3Server(threading.Thread):
    def __init__(self, port=_startPort):
        threading.Thread.__init__(self)
        self.port = port
        self.daemon = True
        self.service = 'http://127.0.0.1:%d' % port
        self.botoConnect = makeBotoConnectParams('abc', '123', self.service)

    def run(self):
        """Start and run the mock S3 server."""
        app = moto.server.DomainDispatcherApplication(_create_app,
                                                      service='s3bucket_path')
        moto.server.run_simple('0.0.0.0', self.port, app, threaded=True)


def _create_app(service):
    """
    Create the S3 server using moto, altering the responses to allow CORS
    requests.
    :param service: the amazon service we wish to mimic.  This should probably
                    be 's3bucket_path'.
    """
    app = moto.server.create_backend_app(service)

    # I would have preferred to set the CORS for the bucket we have, but moto
    # doesn't support that, so I have to add the values here.
    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods',
                             'HEAD, GET, PUT, POST, OPTIONS, DELETE')
        response.headers.add(
            'Access-Control-Allow-Headers',
            'Content-Disposition,Content-Type,'
            'x-amz-meta-authorized-length,x-amz-acl,x-amz-meta-uploader-ip,'
            'x-amz-meta-uploader-id'
            )
        response.headers.add('Access-Control-Expose-Headers', 'ETag')
        return response

    return app


if __name__ == '__main__':
    """
    Provide a simple stand-alone program so that developers can run girder with
    a modified conf file to simulate an S3 store.
    """
    parser = argparse.ArgumentParser(
        description='Run a mock S3 server.  All data will be lost when it is '
        'stopped.')
    parser.add_argument('-p', '--port', type=int, help='The port to run on',
                        default=_startPort)
    parser.add_argument('-b', '--bucket', type=str,
                        help='The name of a bucket to create', default='')
    parser.add_argument('-v', '--verbose', action='count',
                        help='Increase verbosity.', default=0)
    args = parser.parse_args()
    server = MockS3Server(args.port)
    server.start()
    if args.bucket:
        createBucket(server.botoConnect, args.bucket)
    while True:
        time.sleep(10000)
