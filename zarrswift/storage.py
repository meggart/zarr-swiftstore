# -*- coding: utf-8 -*-

"""
SwiftStore provides openstack swift object storage backend for zarr

This class is developed using zarr.ABSStore as reference
(https://github.com/zarr-developers/zarr-python)
"""

import os
from collections.abc import MutableMapping

from swiftclient.client import Connection
import swiftclient.exceptions
from zarr.util import normalize_storage_path

from numcodecs.compat import ensure_bytes


class SwiftStore(MutableMapping):
    """Storage class using openstack swift object store.

    To establish a connection to swift object store, provide (authurl, user, key)
    or (preauthurl, preauthtoken). Other way to provide these values is through
    os.environ. (ST_AUTH, ST_USER, ST_KEY) or (OS_STORAGE_URL, OS_AUTH_TOKEN)

    Parameters
    ----------
    container: string
        The name of the swift object container
    prefix: string
        sub-directory path with in the container to store data
    authurl: string
        authentication url
    user: string
        user details of the form "account:user"
    key: string
        key is password
    preauthurl: string
        storage-url
    preauthtoken: string
        pre-authenticated token to aceess object storage
    """
    def __init__(self, container, prefix='', authurl=None, user=None, key=None, preauthurl=None, preauthtoken=None):
        self.container = container
        self.prefix = normalize_storage_path(prefix)
        self.conn = self._make_connection(authurl, user, key, preauthurl, preauthtoken)
        self._ensure_container()
        self._record_keys = set()

    def _make_connection(self, authurl=None, user=None, key=None, preauthurl=None, preauthtoken=None):
        "make a connection object either from pre-authenticated token or using authurl"
        getenv = os.environ.get
        authurl = authurl or getenv('ST_AUTH')
        user = user or getenv('ST_USER')
        key = key or getenv('ST_KEY')
        preauthurl = preauthurl or getenv('OS_STORAGE_URL')
        preauthtoken = preauthtoken or getenv('OS_AUTH_TOKEN')
        if preauthurl and preauthtoken:
            conn = Connection(preauthurl=preauthurl, preauthtoken=preauthtoken)
        elif authurl and user and key:
            conn = Connection(authurl, user=user, key=key)
        else:
            raise ValueError(
            'Missing required (authurl, user, key) or (preauthurl, preauthtoken) '
            'values to establish a connection'
            )
        return conn

    def _ensure_container(self):
        _, contents = self.conn.get_account()
        listings = [item['name'] for item in contents]
        if self.container not in listings:
            self.conn.put_container(self.container)

    def _add_prefix(self, path):
        path = '/'.join([self.prefix, path])
        return normalize_storage_path(path)

    # def __getitem__(self, name):
    #     name = self._add_prefix(name)
    #     try:
    #         resp, content = self.conn.get_object(self.container, name)
    #     except swiftclient.exceptions.ClientException:
    #         raise KeyError('Object {} not found'.format(name))
    #     return content

    def __getitem__(self, name):
        name = self._add_prefix(name)
        if name in self._record_keys:
            _, content = self.conn.get_object(self.container, name)
        else:
            raise KeyError('Object {} not found'.format(name))
        return content

    def __setitem__(self, name, value):
        name = self._add_prefix(name)
        value = ensure_bytes(value)
        self.conn.put_object(self.container, name, value)
        self._record_keys.add(name)

    # def __delitem__(self, name):
    #     name = self._add_prefix(name)
    #     try:
    #         self.conn.delete_object(self.container, name)
    #     except swiftclient.exceptions.ClientException:
    #         raise KeyError('Object {} not found'.format(name))

    def __delitem__(self, name):
        name = self._add_prefix(name)
        if name in self._record_keys:
            self.conn.delete_object(self.container, name)
            self._record_keys.remove(name)
        else:
            raise KeyError('Object {} not found'.format(name))

    def __eq__(self, other):
        return (
            isinstance(other, SwiftStore) and
            self.container == other.container and
            self.prefix == other.prefix
        )

    def listdir(self, path=None, with_prefix=False):
        if path is None:
            path = self.prefix
        else:
            path = self._add_prefix(path)
        _, contents = self.conn.get_container(self.container, prefix=path)
        listings = [entry['name'] for entry in contents]
        if not with_prefix and self.prefix:
            # remove prefix length + trailing slash
            prefix_size = len(self.prefix) + 1
            listings = [entry[prefix_size:] for entry in listings]
        return listings

    def __contains__(self, name):
        return name in self.listdir()

    def __iter__(self):
        for entry in self.listdir():
            yield entry

    def keys(self):
        return list(self.__iter__())

    def __len__(self):
        return len(self.keys())

    def getsize(self, path=None):
        'container or object size in bytes'
        path = self.prefix if path is None else self._add_prefix(path)
        if path:
            content = self.conn.head_object(self.container, path)
            size = int(content['content-length'])
            return size
        content = self.conn.head_container(self.container)
        size = int(content['x-container-bytes-used'])
        return size

    def rmdir(self, path=None):
        for entry in self.listdir(path, with_prefix=True):
            self.conn.delete_object(self.container, entry)
        return

    def clear(self):
        self.rmdir()