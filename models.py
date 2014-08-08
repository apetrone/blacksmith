import os
import fnmatch
import json
import logging
import shutil
import shlex
import subprocess

from util import (
	get_platform,
	run_as_shell
)

#
# Exceptions
#
class UnknownToolException(Exception):
	pass


#
# Classes
#
class AssetFolderMask(object):
	def __init__(self, *args, **kwargs):
		self.glob = kwargs.get("glob", None)
		self.src_folder, self.glob = self.glob.split("/")
		self.dst_folder = kwargs.get("destination", self.src_folder)
		self.tool = kwargs.get("tool", None)
		self.params = kwargs.get("params", {})
		self.abs_regex = None

	def make_folders_absolute(self, asset_source_path, asset_destination_path):
		self.abs_src_folder = os.path.join(
			asset_source_path, self.src_folder
		)
		self.abs_dst_folder = os.path.join(
			asset_destination_path, self.dst_folder
		)

	def get_abs_regex(self):
		if not self.abs_regex:
			self.abs_regex = fnmatch.translate(
				os.path.join(self.abs_src_folder, self.glob)
			)
		return self.abs_regex

class AttributeStore(object):
	def __init__(self, *initial_data, **kwargs):
		for dictionary in initial_data:
			for key in dictionary:
				setattr(self, key, dictionary[key])
		for key in kwargs:
			setattr(self, key, kwargs[key])

	def __iter__(self):
		for i in self.__dict__.items():
			yield i

	def merge(self, other):
		for key, value in other.__dict__.iteritems():
			attrib = getattr(self, key, None)
			if attrib:
				if type(value) == list and type(attrib) == list:
					attrib.extend(value)
				elif type(value) == dict and type(attrib) == dict:
					attrib.update(value)
				elif type(attrib) == unicode or type(attrib) == str:
					attrib = value
				else:
					raise Exception(
						"Unknown conflict types \"%s\" <-> \"%s\"!"
						% (type(attrib), type(value))
					)
			else:
				self.__dict__[key] = value

class Cache(object):
	CACHE_EXTENSION = "cache"

	CACHE_ADDED = 0
	CACHE_UPDATED = 1
	CACHE_IS_NEWER = 2


	ALTER_TABLE = {
		CACHE_ADDED: "A", # added
		CACHE_UPDATED: "M", # modified
		CACHE_IS_NEWER: "O"  # ignored
	}	

	def __init__(self, relative_config_path, remove=False):
		# derive the cache path from the relative relative_config path
		relative_cache_path = os.path.splitext(
			relative_config_path
		)[0] + ".%s" % Cache.CACHE_EXTENSION
	
		# init variables
		self.abs_cache_path = os.path.abspath(relative_cache_path)
		self.cache = {}

		# remove if requested
		if remove:
			self.remove()

	def load(self):
		if os.path.exists(self.abs_cache_path):
			logging.info("Reading cache from %s..." % self.abs_cache_path)
			with open(self.abs_cache_path, "rb") as file:
				self.cache = json.load(file)
				file.close()

	def save(self):
		logging.info("Writing cache %s..." % self.abs_cache_path)
		with open(self.abs_cache_path, "wb") as file:
			file.write(json.dumps(self.cache, indent=4))

	def update(self, abs_asset_path):
		"""
			Update the cache with the modified file time for
			the file at abs_asset_path.

			Return true if the abs_asset_path modtime is > the
			cached modtime.

			Otherwise, return False
		"""

		# get the new modified time
		modtime = os.path.getmtime(abs_asset_path)

		# keep track of status
		status = Cache.CACHE_ADDED

		# compare that value to the cached value
		# update if necessary
		# 
		if abs_asset_path in self.cache:
			if modtime <= self.cache[abs_asset_path]:
				status = Cache.CACHE_IS_NEWER
				return False
			else:
				status = Cache.CACHE_UPDATED
		else:
			status = Cache.CACHE_ADDED

		logging.info(
			"%c -> %s" %
		 	(Cache.ALTER_TABLE[status], abs_asset_path)
		)

		self.cache[abs_asset_path] = modtime
		if status == Cache.CACHE_IS_NEWER:
			return False

		return True

	def remove(self):
		if os.path.exists(self.abs_cache_path):
			os.unlink(self.abs_cache_path)

class Tool(object):
	def __init__(self, *args, **kwargs):
		self.name = kwargs.get("name", None)
		
		data = kwargs.get("data", None)
		if data is None:
			logging.warn("Tool data missing! Unable to parse tool.")
			raise Exception("Missing tool data")

		self.platforms = data.get("platforms", None)
		self.commands = data.get("commands", [])

	def __str__(self):
		return "Tool [Name=%s, Commands=%i]" % (self.name, len(self.commands))

	def execute(self, params):
		if self.platforms and params["platform"] in self.platforms:
			params["tool"] = self.platforms[params["platform"]]
		else:
			# no platforms specified for this tool; default to the tool name
			params["tool"] = self.name

		for raw_cmd in self.commands:
			try:
				cmd = (raw_cmd % params).encode("ascii")
			except TypeError as e:
				logging.error(raw_cmd)
				logging.error(params)

			runnable = shlex.split(cmd)
			try:			
				returncode = subprocess.call(runnable, shell=run_as_shell())
				if returncode != 0:
					logging.error("ERROR %s" % cmd)
			except OSError as exc:
				logging.error("ERROR executing \"%s\", %s" % (cmd, exc))

class CopyTool(Tool):
	def __init__(self):
		super(CopyTool, self).__init__(name="copy", data={})

	def execute(self, params):
		try:
			# logging.debug(
			# 	"[COPY] %s -> %s" %
			# 	(params["src_file_path"], params["dst_file_path"])
			# )
			shutil.copyfile(params["src_file_path"], params["dst_file_path"])
		except IOError as exc:
			logging.info("IOError: %s" % exc)

class MoveTool(Tool):
	def __init__(self):
		super(MoveTool, self).__init__(name="move", data={})

	def execute(self, params):
		try:
			shutil.move(params["src_file_path"], params["dst_file_path"])
		except:
			raise
