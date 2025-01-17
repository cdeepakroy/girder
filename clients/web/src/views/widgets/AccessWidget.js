/**
 * This view allows users to see and control access on a resource.
 */
girder.views.AccessWidget = girder.View.extend({
    events: {
        'click button.g-save-access-list': 'saveAccessList',
        'click a.g-action-remove-access': 'removeAccessEntry',
        'change .g-public-container .radio input': 'privacyChanged'
    },

    initialize: function (settings) {
        this.modelType = settings.modelType;

        this.searchWidget = new girder.views.SearchFieldWidget({
            placeholder: 'Start typing a name...',
            types: ['group', 'user'],
            parentView: this
        }).on('g:resultClicked', this.addEntry, this);

        if (this.model.get('access')) {
            this.render();
        } else {
            this.model.on('g:accessFetched', function () {
                this.render();
            }, this).fetchAccess();
        }
    },

    render: function () {
        var closeFunction;
        if (this.modelType === 'folder') {
            girder.dialogs.handleOpen('folderaccess');
            closeFunction = function () {
                girder.dialogs.handleClose('folderaccess');
            };
        } else {
            girder.dialogs.handleOpen('access');
            closeFunction = function () {
                girder.dialogs.handleClose('access');
            };
        }
        this.$el.html(girder.templates.accessEditor({
            model: this.model,
            modelType: this.modelType,
            public: this.model.get('public')
        })).girderModal(this).on('hidden.bs.modal', closeFunction);

        _.each(this.model.get('access').groups, function (groupAccess) {
            this.$('#g-ac-list-groups').append(girder.templates.accessEntry({
                accessTypes: girder.AccessType,
                type: 'group',
                entry: _.extend(groupAccess, {
                    title: groupAccess.name,
                    subtitle: groupAccess.description
                })
            }));
        }, this);

        _.each(this.model.get('access').users, function (userAccess) {
            this.$('#g-ac-list-users').append(girder.templates.accessEntry({
                accessTypes: girder.AccessType,
                type: 'user',
                entry: _.extend(userAccess, {
                    title: userAccess.name,
                    subtitle: userAccess.login
                })
            }));
        }, this);

        this._makeTooltips();

        this.searchWidget.setElement(this.$('.g-search-field-container')).render();

        this.privacyChanged();

        return this;
    },

    _makeTooltips: function () {
        this.$('.g-action-remove-access').tooltip({
            placement: 'bottom',
            animation: false,
            delay: {show: 100}
        });
    },

    /**
     * Add a new user or group entry to the access control list UI. If the
     * given user or group already has an entry there, this does nothing.
     */
    addEntry: function (entry) {
        this.searchWidget.resetState();
        if (entry.type === 'user') {
            this._addUserEntry(entry);
        } else if (entry.type === 'group') {
            this._addGroupEntry(entry);
        }
    },

    _addUserEntry: function (entry) {
        var exists = false;
        _.every(this.$('.g-user-access-entry'), function (el) {
            if ($(el).attr('resourceid') === entry.id) {
                exists = true;
            }
            return !exists;
        }, this);

        if (!exists) {
            var model = new girder.models.UserModel();
            model.set('_id', entry.id).on('g:fetched', function () {
                this.$('#g-ac-list-users').append(girder.templates.accessEntry({
                    accessTypes: girder.AccessType,
                    type: 'user',
                    entry: {
                        title: model.name(),
                        subtitle: model.get('login'),
                        id: entry.id,
                        level: girder.AccessType.READ
                    }
                }));

                this._makeTooltips();
            }, this).fetch();
        }
    },

    _addGroupEntry: function (entry) {
        var exists = false;
        _.every(this.$('.g-group-access-entry'), function (el) {
            if ($(el).attr('resourceid') === entry.id) {
                exists = true;
            }
            return !exists;
        }, this);

        if (!exists) {
            var model = new girder.models.GroupModel();
            model.set('_id', entry.id).on('g:fetched', function () {
                this.$('#g-ac-list-groups').append(girder.templates.accessEntry({
                    accessTypes: girder.AccessType,
                    type: 'group',
                    entry: {
                        title: model.name(),
                        subtitle: model.get('description'),
                        id: entry.id,
                        level: girder.AccessType.READ
                    }
                }));

                this._makeTooltips();
            }, this).fetch();
        }
    },

    saveAccessList: function (event) {
        $(event.currentTarget).attr('disabled', 'disabled');

        // Rebuild the access list
        var acList = {
            users: [],
            groups: []
        };

        _.each(this.$('.g-group-access-entry'), function (el) {
            var $el = $(el);
            acList.groups.push({
                name: $el.find('.g-desc-title').html(),
                id: $el.attr('resourceid'),
                level: parseInt(
                    $el.find('.g-access-col-right>select').val(),
                    10
                )
            });
        }, this);

        _.each(this.$('.g-user-access-entry'), function (el) {
            var $el = $(el);
            acList.users.push({
                login: $el.find('.g-desc-subtitle').html(),
                name: $el.find('.g-desc-title').html(),
                id: $el.attr('resourceid'),
                level: parseInt(
                    $el.find('.g-access-col-right>select').val(),
                    10
                )
            });
        }, this);

        this.model.set({
            access: acList,
            public: this.$('#g-access-public').is(':checked')
        });

        var recurse = this.$('#g-apply-recursive').is(':checked');

        this.model.off('g:accessListSaved')
                  .on('g:accessListSaved', function () {
                      this.$el.modal('hide');
                      this.trigger('g:accessListSaved', {
                          recurse: recurse
                      });
                  }, this).updateAccess({
                      recurse: recurse,
                      progress: true
                  });
    },

    removeAccessEntry: function (event) {
        var sel = '.g-user-access-entry,.g-group-access-entry';
        $(event.currentTarget).tooltip('hide').parents(sel).remove();
    },

    privacyChanged: function () {
        this.$('.g-public-container .radio').removeClass('g-selected');
        var selected = this.$('.g-public-container .radio input:checked');
        selected.parents('.radio').addClass('g-selected');
    }
});
