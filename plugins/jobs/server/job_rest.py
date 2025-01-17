#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright Kitware Inc.
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

import pymongo

from girder import events
from girder.api import access
from girder.api.describe import Description
from girder.api.rest import Resource, loadmodel
from girder.constants import AccessType


class Job(Resource):
    def __init__(self):
        self.resourceName = 'job'

        self.route('GET', (), self.listJobs)
        self.route('GET', (':id',), self.getJob)
        self.route('PUT', (':id',), self.updateJob)
        self.route('DELETE', (':id',), self.deleteJob)

    @access.public
    def listJobs(self, params):
        limit, offset, sort = self.getPagingParameters(
            params, 'created', pymongo.DESCENDING)
        currentUser = self.getCurrentUser()
        userId = params.get('userId')
        if not userId:
            user = currentUser
        elif userId.lower() == 'none':
            user = None
        else:
            user = self.model('user').load(
                params['userId'], user=currentUser, level=AccessType.READ)

        jobs = self.model('job', 'jobs').list(
            user=user, offset=offset, limit=limit, sort=sort,
            currentUser=currentUser)
        return [self.model('job', 'jobs').filter(job, user) for job in jobs]
    listJobs.description = (
        Description('List jobs for a given user.')
        .param('userId', 'The ID of the user whose jobs will be listed. If '
               'not passed or empty, will use the currently logged in user. If '
               'set to "None", will list all jobs that do not have an owning '
               'user.', required=False)
        .pagingParams(defaultSort='created', defaultSortDir=pymongo.DESCENDING))

    @access.public
    @loadmodel(model='job', plugin='jobs', level=AccessType.READ)
    def getJob(self, job, params):
        return self.model('job', 'jobs').filter(job, self.getCurrentUser())
    getJob.description = (
        Description('Get a job by ID.')
        .param('id', 'The ID of the job.', paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the job.', 403))

    @access.token
    @loadmodel(model='job', plugin='jobs', force=True)
    def updateJob(self, job, params):
        user = self.getCurrentUser()
        if user is None:
            self.ensureTokenScopes('jobs.job_' + str(job['_id']))
        else:
            self.model('job', 'jobs').requireAccess(
                job, user, level=AccessType.WRITE)

        event = events.trigger('jobs.job.update', {
            'job': job,
            'params': params
        })

        if not event.defaultPrevented:
            job = self.model('job', 'jobs').updateJob(
                job, log=params.get('log'), status=params.get('status'),
                overwrite=self.boolParam('overwrite', params, False),
                notify=self.boolParam('notify', params, default=True),
                progressCurrent=params.get('progressCurrent'),
                progressTotal=params.get('progressTotal'),
                progressMessage=params.get('progressMessage'))

        return job
    updateJob.description = (
        Description('Update an existing job.')
        .notes('In most cases, regular users should not call this endpoint. It '
               'will typically be used by a batch processing system to send '
               'updates regarding the execution of the job. If using a non-'
               'user-associated token for authorization, the token must be '
               'granted the "jobs.job_<id>" scope, where <id> is the ID of '
               'the job being updated.')
        .param('id', 'The ID of the job.', paramType='path')
        .param('log', 'A message to add to the job\'s log field. If you want '
               'to overwrite any existing log content, pass another parameter '
               '"overwrite=true".', required=False)
        .param('overwrite', 'If passing a log parameter, you may set this to '
               '"true" if you wish to overwrite the log field rather than '
               'append to it. The default behavior is to append',
               dataType='boolean', required=False)
        .param('status', 'Update the status of the job. See the JobStatus '
               'enumeration in the constants module in this plugin for the '
               'numerical values of each status.', dataType='integer',
               required=False)
        .param('progressTotal', 'Maximum progress value, set <= 0 to indicate '
               'indeterminate progress for this job.', required=False)
        .param('progressCurrent', 'Current progress value.', required=False)
        .param('progressMessage', 'Current progress message.', required=False)
        .param('notify', 'If this update should trigger a notification, set '
               'this field to true. The default is true.', dataType='boolean',
               required=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the job.', 403))

    @access.user
    @loadmodel(model='job', plugin='jobs', level=AccessType.ADMIN)
    def deleteJob(self, job, params):
        self.model('job', 'jobs').remove(job)
    deleteJob.description = (
        Description('Delete an existing job.')
        .param('id', 'The ID of the job.', paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the job.', 403))
