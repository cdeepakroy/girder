#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright 2013 Kitware Inc.
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

import cherrypy
import os
import psutil
import shutil
import six
import stat
import tempfile

from six import BytesIO
from hashlib import sha512
from . import sha512_state
from .abstract_assetstore_adapter import AbstractAssetstoreAdapter
from girder.models.model_base import ValidationException, GirderException
from girder import logger
from girder.utility import progress

BUF_SIZE = 65536


class FilesystemAssetstoreAdapter(AbstractAssetstoreAdapter):
    """
    This assetstore type stores files on the filesystem underneath a root
    directory. Files are named by their SHA-512 hash, which avoids duplication
    of file content.

    :param assetstore: The assetstore to act on.
    :type assetstore: dict
    """

    @staticmethod
    def validateInfo(doc):
        """
        Makes sure the root field is a valid absolute path and is writeable.
        It also conveniently update the root field replacing the initial
        component by the user home directory running the server if it matches
        ``~`` or ``~user``.
        """
        doc['root'] = os.path.expanduser(doc['root'])

        if not os.path.isabs(doc['root']):
            raise ValidationException('You must provide an absolute path '
                                      'for the root directory.', 'root')
        if not os.path.isdir(doc['root']):
            try:
                os.makedirs(doc['root'])
            except OSError:
                raise ValidationException('Could not make directory "{}".'
                                          .format(doc['root'], 'root'))
        if not os.access(doc['root'], os.W_OK):
            raise ValidationException('Unable to write into directory "{}".'
                                      .format(doc['root'], 'root'))

    @staticmethod
    def fileIndexFields():
        """
        File documents should have an index on their sha512 field, as well as
        whether or not they are imported.
        """
        return ['sha512', 'imported']

    def __init__(self, assetstore):
        self.assetstore = assetstore
        # If we can't create the temp directory, the assetstore still needs to
        # be initialized so that it can be deleted or modified.  The validation
        # prevents invalid new assetstores from being created, so this only
        # happens to existing assetstores that no longer can access their temp
        # directories.
        self.tempDir = os.path.join(assetstore['root'], 'temp')
        if not os.path.exists(self.tempDir):
            try:
                os.makedirs(self.tempDir)
            except OSError:
                logger.exception('Failed to create filesystem assetstore '
                                 'directories {}'.format(self.tempDir))

    def capacityInfo(self):
        """
        For filesystem assetstores, we just need to report the free and total
        space on the filesystem where the assetstore lives.
        """
        try:
            usage = psutil.disk_usage(self.assetstore['root'])
            return {'free': usage.free, 'total': usage.total}
        except OSError:
            logger.exception(
                'Failed to get disk usage of %s' % self.assetstore['root'])
        # If psutil.disk_usage fails or we can't query the assetstore's root
        # directory, just report nothing regarding disk capacity
        return {  # pragma: no cover
            'free': None,
            'total': None
        }

    def initUpload(self, upload):
        """
        Generates a temporary file and sets its location in the upload document
        as tempFile. This is the file that the chunks will be appended to.
        """
        fd, path = tempfile.mkstemp(dir=self.tempDir)
        os.close(fd)  # Must close this file descriptor or it will leak
        upload['tempFile'] = path
        upload['sha512state'] = sha512_state.serializeHex(sha512())
        return upload

    def uploadChunk(self, upload, chunk):
        """
        Appends the chunk into the temporary file.
        """
        # If we know the chunk size is too large or small, fail early.
        self.checkUploadSize(upload, self.getChunkSize(chunk))

        if isinstance(chunk, six.text_type):
            chunk = chunk.encode('utf8')

        if isinstance(chunk, six.binary_type):
            chunk = BytesIO(chunk)

        # Restore the internal state of the streaming SHA-512 checksum
        checksum = sha512_state.restoreHex(upload['sha512state'])

        if self.requestOffset(upload) > upload['received']:
            # This probably means the server died midway through writing last
            # chunk to disk, and the database record was not updated. This means
            # we need to update the sha512 state with the difference.
            with open(upload['tempFile'], 'rb') as tempFile:
                tempFile.seek(upload['received'])
                while True:
                    data = tempFile.read(BUF_SIZE)
                    if not data:
                        break
                    checksum.update(data)

        with open(upload['tempFile'], 'a+b') as tempFile:
            size = 0
            while not upload['received'] + size > upload['size']:
                data = chunk.read(BUF_SIZE)
                if not data:
                    break
                size += len(data)
                tempFile.write(data)
                checksum.update(data)
        chunk.close()

        try:
            self.checkUploadSize(upload, size)
        except ValidationException:
            with open(upload['tempFile'], 'a+b') as tempFile:
                tempFile.truncate(upload['received'])
            raise

        # Persist the internal state of the checksum
        upload['sha512state'] = sha512_state.serializeHex(checksum)
        upload['received'] += size
        return upload

    def requestOffset(self, upload):
        """
        Returns the size of the temp file.
        """
        return os.stat(upload['tempFile']).st_size

    def finalizeUpload(self, upload, file):
        """
        Moves the file into its permanent content-addressed location within the
        assetstore. Directory hierarchy yields 256^2 buckets.
        """
        hash = sha512_state.restoreHex(upload['sha512state']).hexdigest()
        dir = os.path.join(hash[0:2], hash[2:4])
        absdir = os.path.join(self.assetstore['root'], dir)

        path = os.path.join(dir, hash)
        abspath = os.path.join(self.assetstore['root'], path)

        if not os.path.exists(absdir):
            os.makedirs(absdir)

        if os.path.exists(abspath):
            # Already have this file stored, just delete temp file.
            os.remove(upload['tempFile'])
        else:
            # Move the temp file to permanent location in the assetstore.
            # shutil.move works across filesystems
            shutil.move(upload['tempFile'], abspath)
            try:
                os.chmod(abspath, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                # some filesystems may not support POSIX permissions
                pass

        file['sha512'] = hash
        file['path'] = path

        return file

    def fullPath(self, file):
        """
        Utility method for constructing the full (absolute) path to the given
        file.
        """
        if file.get('imported'):
            return file['path']
        else:
            return os.path.join(self.assetstore['root'], file['path'])

    def downloadFile(self, file, offset=0, headers=True, endByte=None,
                     **kwargs):
        """
        Returns a generator function that will be used to stream the file from
        disk to the response.
        """
        if endByte is None or endByte > file['size']:
            endByte = file['size']

        path = self.fullPath(file)

        if not os.path.isfile(path):
            raise GirderException(
                'File %s does not exist.' % path,
                'girder.utility.filesystem_assetstore_adapter.'
                'file-does-not-exist')

        if headers:
            cherrypy.response.headers['Accept-Ranges'] = 'bytes'
            self.setContentHeaders(file, offset, endByte)

        def stream():
            bytesRead = offset
            with open(path, 'rb') as f:
                if offset > 0:
                    f.seek(offset)

                while True:
                    readLen = min(BUF_SIZE, endByte - bytesRead)
                    if readLen <= 0:
                        break

                    data = f.read(readLen)
                    bytesRead += readLen

                    if not data:
                        break
                    yield data

        return stream

    def deleteFile(self, file):
        """
        Deletes the file from disk if it is the only File in this assetstore
        with the given sha512. Imported files are not actually deleted.
        """
        if file.get('imported'):
            return

        q = {
            'sha512': file['sha512'],
            'assetstoreId': self.assetstore['_id']
        }
        matching = self.model('file').find(q, limit=2, fields=[])
        if matching.count(True) == 1:
            path = os.path.join(self.assetstore['root'], file['path'])
            if os.path.isfile(path):
                os.remove(path)

    def cancelUpload(self, upload):
        """
        Delete the temporary files associated with a given upload.
        """
        if os.path.exists(upload['tempFile']):
            os.unlink(upload['tempFile'])

    def importFile(self, item, path, user, name=None, mimeType=None, **kwargs):
        """
        Import a single file from the filesystem into the assetstore.

        :param item: The parent item for the file.
        :type item: dict
        :param path: The path on the local filesystem.
        :type path: str
        :param user: The user to list as the creator of the file.
        :type user: dict
        :param name: Name for the file. Defaults to the basename of ``path``.
        :type name: str
        :param mimeType: MIME type of the file if known.
        :type mimeType: str
        :returns: The file document that was created.
        """
        stat = os.stat(path)
        name = name or os.path.basename(path)

        file = self.model('file').createFile(
            name=name, creator=user, item=item, reuseExisting=True,
            assetstore=self.assetstore, mimeType=mimeType, size=stat.st_size)
        file['path'] = os.path.abspath(os.path.expanduser(path))
        file['mtime'] = stat.st_mtime
        file['imported'] = True
        return self.model('file').save(file)

    def importData(self, parent, parentType, params, progress, user):
        importPath = params['importPath']

        if not os.path.isdir(importPath):
            raise ValidationException('No such directory: %s.' % importPath)

        for name in os.listdir(importPath):
            progress.update(message=name)
            path = os.path.join(importPath, name)

            if os.path.isdir(path):
                folder = self.model('folder').createFolder(
                    parent=parent, name=name, parentType=parentType,
                    creator=user, reuseExisting=True)
                self.importData(folder, 'folder', params={
                    'importPath': os.path.join(importPath, name)
                }, progress=progress, user=user)
            else:
                if parentType != 'folder':
                    raise ValidationException(
                        'Files cannot be imported directly underneath a %s.' %
                        parentType)

                item = self.model('item').createItem(
                    name=name, creator=user, folder=parent, reuseExisting=True)
                self.importFile(item, path, user, name=name)

    def findInvalidFiles(self, progress=progress.noProgress, filters=None,
                         checkSize=True, **kwargs):
        """
        Goes through every file in this assetstore and finds those whose
        underlying data is missing or invalid. This is a generator function --
        for each invalid file found, a dictionary is yielded to the caller that
        contains the file, its absolute path on disk, and a reason for invalid,
        e.g. "missing" or "size".

        :param progress: Pass a progress context to record progress.
        :type progress: :py:class:`girder.utility.progress.ProgressContext`
        :param filters: Additional query dictionary to restrict the search for
            files. There is no need to set the ``assetstoreId`` in the filters,
            since that is done automatically.
        :type filters: dict or None
        :param checkSize: Whether to make sure the size of the underlying
            data matches the size of the file.
        :type checkSize: bool
        """
        filters = filters or {}
        q = dict({
            'assetstoreId': self.assetstore['_id']
        }, **filters)

        cursor = self.model('file').find(q)
        progress.update(total=cursor.count(), current=0)

        for file in cursor:
            progress.update(increment=1, message=file['name'])
            path = self.fullPath(file)

            if not os.path.isfile(path):
                yield {
                    'reason': 'missing',
                    'file': file,
                    'path': path
                }
            elif checkSize and os.path.getsize(path) != file['size']:
                yield {
                    'reason': 'size',
                    'file': file,
                    'path': path
                }
