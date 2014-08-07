import os
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
class AssetFolder(object):
	def __init__(self, *args, **kwargs):
		self.glob = kwargs.get("glob", None)
		self.src_folder, self.glob = self.glob.split("/")
		self.dst_folder = kwargs.get("destination", self.src_folder)
		self.tool = kwargs.get("tool", None)
		self.params = kwargs.get("params", {})

	def make_folders_absolute(self, asset_source_path, asset_destination_path):
		self.abs_src_folder = os.path.join(
			asset_source_path, self.src_folder
		)
		self.abs_dst_folder = os.path.join(
			asset_destination_path, self.dst_folder
		)

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

class CopyCommand(Tool):
	def execute(self, params):
		try:
			# logging.debug(
			# 	"[COPY] %s -> %s" %
			# 	(params["src_file_path"], params["dst_file_path"])
			# )
			shutil.copyfile(params["src_file_path"], params["dst_file_path"])
		except IOError as exc:
			logging.info("IOError: %s" % exc)
