import os
import json

import argparse
import logging
import re
import time
import copy
import socket
import fnmatch
import shutil

from models import (
	AssetFolderMask,
	AttributeStore,
	Cache,
	KeyValueCache,
	WorkingDirectory,
	Tool,
	UnknownToolException
)

from util import(
	execute_commands,
	generate_params_for_file,
	get_platform,
	make_dirs,
	normalize_paths,
	run_as_shell,
	setup_environment,
	strip_trailing_slash,
	type_is_string,
	copy_tree
)

CONFIG_TYPE_MAP = {
	"paths": [dict],
	"tools": [dict],
	"assets": [dict],
	"host_platform": [str, unicode],
	"target_platform": [str, unicode]
}
INCLUDE_KEYWORD = "include"

def verify_config(config, type_map):
	for key, _ in config.iteritems():
		if key in type_map:
			t = type(config[key])
			allowed_types = type_map[key]
			if t not in allowed_types:
				raise Exception("%s not valid type for %s" % (t, key))


def handle_includes(config_cache, config, type_map):
	# only examine the top level keys for the include keyword.

	source_dict = copy.copy(config)

	for source_key, value_data in source_dict.iteritems():
		# source_key is any top-level key. "paths", "tools", "assets"
		if type(value_data) is dict:
			if INCLUDE_KEYWORD in value_data:
				include_list = value_data[INCLUDE_KEYWORD]
				if type_is_string(include_list):
					include_list = [include_list]
				else:
					include_list = include_list

				final_data = config[source_key]
				for include_path in include_list:
					included_config = load_config(
						include_path, 
						config_cache
					)
					result = handle_includes(
						config_cache,
						included_config,
						type_map
					)
					final_data.update(result)

				del config[source_key][INCLUDE_KEYWORD]
				config[source_key] = final_data
	return config

def load_config(path, config_cache):
	config = None

	abs_path = os.path.abspath(
		os.path.join(WorkingDirectory.current_directory(),
		path)
	)

	WorkingDirectory.push(os.path.dirname(path))

	# check the cache first
	if config_cache.contains(abs_path):
		return config_cache.get(abs_path)

	# need to load it from disk
	if os.path.exists(abs_path):
		with open(abs_path, "rb") as file:
			try:
				data_dict = json.load(file)
			except:
				logging.info("error reading %s" % abs_path)
				raise

		config_cache.set(abs_path, data_dict)

		config = handle_includes(config_cache, data_dict, CONFIG_TYPE_MAP)
	else:
		raise Exception(
			"load_config: config \"%s\" does not exist" % abs_path
		)


	WorkingDirectory.pop()

	return config

def monitor_assets(
		cache, 
		settings, 
		asset_folders,
		tools, 
		platform,
		server_url
	):

	try:
		import watchdog
		from watchdog.events import FileSystemEventHandler, LoggingEventHandler
		from watchdog.observers import Observer
	except:
		logging.error("Unable to import watchdog. It is required for monitoring!")
		raise



	# experimental for reload requests (should use requests lib)
	import httplib


	class Apprentice(watchdog.events.FileSystemEventHandler):
		"""
			The apprentice will help us out by monitoring the paths we
			are interested in.
		"""

		def __init__(
				self,
				cache,
				settings,
				asset_folders,
				tools,
				platform,
				server_url = None
			):
			self.cache = cache
			self.settings = settings
			self.asset_folders = asset_folders
			self.tools = tools
			self.platform = platform
			
			self.server_url = None
			if server_url and server_url.startswith("http://"):
				self.server_url = server_url[7:]

			self.send_reload_requests = self.server_url != None
			self.queue = []

		def handle_event(self, event):
			source_path = event.src_path
			destination_path = ""

			target_path = event.src_path
			if hasattr(event, "dest_path"):
				target_path = event.dest_path
				destination_path = event.dest_path

			#logging.info("%s | %s" % (source_path, destination_path))
			self.queue.append(target_path)

		def on_created(self, event):
			self.handle_event(event)

		def on_deleted(self, event):
			# For now, we don't handle deletions
			pass
			#self.handle_event(event)

		def on_modified(self, event):
			self.handle_event(event)

		def on_moved(self, event):
			self.handle_event(event)

		def process_events(self):
			queued_items = self.queue[:]
			self.queue = []

			for target_path in queued_items:
				for asset in asset_folders:
					match = re.search(asset.get_abs_regex(), target_path)
					if match:

						# determine if this is a directory path
						# a file in a subdirectory
						source_to_target_path = os.path.relpath(target_path, self.settings.paths.source_root)
						asset_target_relative = os.path.relpath(source_to_target_path, asset.src_folder)
						subdir = os.path.sep in asset_target_relative
						is_directory = os.path.isdir(target_path) or subdir

						if is_directory:
							# We don't want to perform tree copies for modified files
							# inside of a subfolder; only do that on the root subfolder.
							if not subdir:
								source_path = target_path
								destination_path = os.path.join(settings.paths.destination_root, asset.dst_folder, asset_target_relative)
								copy_tree(source_path, destination_path)
							break
						
						try:
							# try to update the cache
							if not self.cache.update(target_path):
								break

							if self.tools.has_key(asset.tool):
								tool = tools[asset.tool]
							else:
								raise UnknownToolException(
									"Unknown tool \"%s\"" % asset.tool
								)

							outputs = execute_commands(
								self.tools, 
								tool, 
								self.settings.paths,
								asset,
								target_path,
								self.platform
							)

							# get the relative asset path from the source_root
							# to the asset being modified.
							relative_path = os.path.relpath(outputs[0], settings.paths.destination_root)

							if self.send_reload_requests:
								request_packet = {
									"type": "file_modified",
									"resource": relative_path
								}
								
								post = 80
								host, uri = self.server_url.split("/")
								if ":" in host:
									host, port = host.split(":")
									port = int(port)

								try:
									connection = httplib.HTTPConnection(host, port)
									connection.request("PUT", ("/" + uri), json.dumps(request_packet))
									response = connection.getresponse()
									if response.status != 204 and response.status != 200:
										logging.warn("Request failed: (%i) %s" % (response.status, response.reason))				
								except socket.error as exception:
									pass
								except:
									raise
							break
						except:
							raise

	logging.info("Monitoring assets in: %s..." % settings.paths.source_root)

	event_handler = Apprentice(
		cache,
		settings,
		asset_folders,
		tools,
		platform,
		server_url
	)

	observer = Observer()
	observer.schedule(event_handler, settings.paths.source_root, recursive=True)
	observer.start()

	import time
	import sys
	try:
		while True:
			# Wait some time for events to trickle in and file i/o
			# to complete
			time.sleep(2)

			# handle events that have been queued
			event_handler.process_events()
	except KeyboardInterrupt:
		observer.stop()

	observer.join()


def iterate_assets(
		cache, 
		settings, 
		asset_folders,
		tools, 
		platform
	):
	# loop through each asset path and glob
	# run the tool associated with each file
	logging.info("Running tools on assets...")
	total_files = 0
	modified_files = 0
	for asset in asset_folders:
		try:
			search_path = os.path.join(
				asset.abs_src_folder, 
				asset.glob
			)
			#logging.info("Processing: \"%s\"" % search_path)
			
			if tools.has_key(asset.tool):
				tool = tools[asset.tool]
			else:
				raise UnknownToolException(
					"Unknown tool \"%s\"" % asset.tool
				)

			path_created = False

			for root, subs, files in os.walk(asset.abs_src_folder, topdown=True):
				# filter files based on glob
				files[:] = fnmatch.filter(files, asset.glob)

				if not path_created:
					# make all asset destination folders
					make_dirs(asset.abs_dst_folder)
					path_created = True

				# filter subdirectories based on the glob
				matched_subs = fnmatch.filter(subs, asset.glob)

				# do not recurse into subdirectories
				subs[:] = []

				if matched_subs:
					# One or more subdirectories matched the glob.
					# For now, copy each match over to the destination folder.
					# This is to specifically handle the case where directories are entire
					# folders (.dSYM, .app). These specific dirs should be
					# exceptions where the entire folder is simply copied.
					for folder in matched_subs:
						copy_tree(source_file_root, dst_file_root)

				for file in files:
					src_file_path = os.path.join(root, file)

					total_files += 1

					if not cache.update(src_file_path):
						continue

					modified_files += 1

					execute_commands(
						tools, 
						tool, 
						settings.paths,
						asset,
						src_file_path,
						platform
					)

		except UnknownToolException as e:
			logging.warn(e.message)
			continue	


	logging.info("Complete.")
	logging.info("Modified / Total - %i/%i" % (modified_files, total_files))

def main():
	commands = {}
	config = None
	ignore_list = []
	settings = AttributeStore()
	tools = {}
	asset_folders = []
	
	p = argparse.ArgumentParser()
	p.add_argument(
		"-c",
		"--config", 
		dest="config_path", 
		metavar="CONFIG_FILE_PATH",
		help="Configuration file path to use when converting assets",
		required=True
	)

	p.add_argument(
		"-p",
		"--platform",
		dest="platform"
	)
	p.add_argument(
		"-y",
		"--clear-cache",
		dest="clear_cache",
		action="store_true"
	)
	p.add_argument(
		"-s",
		"--source_root",
		dest="source_root"
	)

	args = p.parse_args()
	config_cache = KeyValueCache()

	# load config
	config_data = load_config(args.config_path, config_cache)
	
	# the source_root can be specified on the command line;
	# this properly inserts it into the paths dict
	if "paths" in config_data:
		if "source_root" not in config_data["paths"]:
			if not args.source_root:
				raise Exception(
						"source_root is missing. This should be defined"
						" in a config file, or on the command line."
					)				
			else:
				# this path SHOULD be an absolute path
				config_data["paths"]["source_root"] = args.source_root

	config = AttributeStore(config_data)

	if not args.platform:
		args.platform = get_platform()
		logging.info("Target Platform is \"%s\"" % args.platform)


	# load tools
	tools_path = os.path.abspath(
		os.path.join(
		WorkingDirectory.current_directory(),
		os.path.dirname(__file__),
		"tools.conf"
		)
	)

	# get cache path
	cache = Cache(args.config_path, remove=args.clear_cache)
	cache.load()

	# conform all paths
	if getattr(config, "paths", None):
		base_path = os.path.dirname(os.path.abspath(args.config_path))

		# setup environment variables, path, etc.
		config.paths = setup_environment(base_path, config.paths, args.platform)
		
		setattr(settings, "paths", AttributeStore(config.paths))


	# parse all tools
	Tool.load_tools(
		tools,
		tools_path,
		config.tools
	)

	logging.info("Loaded %i tools." % len(tools.items()))

	# parse asset folders
	for asset_glob in config.assets:
		data = dict(
			{u"glob" : asset_glob}.items() +
			config.assets[asset_glob].items()
		)
		asset_folder = AssetFolderMask(**data)
		asset_folder.make_folders_absolute(
			settings.paths.source_root, 
			settings.paths.destination_root
		)
		asset_folders.append(asset_folder)
	logging.info("Loaded %i asset folders." % len(asset_folders))

	# check if we need to enter monitoring mode
	monitor_mode = hasattr(config, "monitor")
	if monitor_mode:
		monitor = config.monitor
		if not "url" in monitor:
			raise Exception("Monitor block requires a \"url\" parameter")

		# run monitoring
		monitor_assets(
			cache,
			settings,
			asset_folders,
			tools,
			args.platform,
			monitor["url"]
		)
	else:
		# just run through all assets
		iterate_assets(
			cache,
			settings,
			asset_folders,
			tools, 
			args.platform
		)

	# write cache to file
	cache.save()

if __name__ == "__main__":
	# initialize logging
	logging.basicConfig(level=logging.INFO)

	main()
