import os
import json

import argparse
from glob import iglob
import logging
import re
import time

from models import (
	AssetFolderMask,
	AttributeStore,
	Cache,
	CopyCommand,
	Tool,
	UnknownToolException
)

from util import(
	generate_params_for_file,
	get_platform,
	load_tools,
	make_dirs,
	normalize_paths,
	run_as_shell,
	setup_environment,
	strip_trailing_slash,
	type_is_string
)



included_configs = []
def load_config(path):
	global included_configs

	config = None
	path = os.path.abspath(path)
	if os.path.exists(path) and (path not in included_configs):
		included_configs.append(path)

		with open(path, "rb") as file:
			cfg = json.load(file)
		
		config = AttributeStore(cfg)

		if getattr(config, "include", None):
			# assume an include is relative
			base_path = os.path.dirname(path)
			config_path = os.path.abspath(
				os.path.join(base_path,config.include)
			)
			newconfig = load_config(config_path)

			if newconfig:
				newconfig.merge(config)
				return newconfig
	else:
		logging.error(
			"load_config: config \"%s\" does not exist or was "
			"already included." % path
		)

	return config

def monitor_assets(
		cache, 
		settings, 
		asset_folders,
		tools, 
		platform
	):

	try:
		import watchdog
		from watchdog.events import FileSystemEventHandler, LoggingEventHandler
		from watchdog.observers import Observer
	except:
		logging.error("Unable to import watchdog. It is required for monitoring!")
		raise

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
				platform
			):
			self.cache = cache
			self.settings = settings
			self.asset_folders = asset_folders
			self.tools = tools
			self.platform = platform

		def show_event(self, event):
			# logging.info("event_type: %s" % event.event_type)
			# logging.info("is_directory: %s" % event.is_directory)
			# 
			# logging.info("src_path: %s" % event.src_path)


			# if hasattr(event, "dest_path"):
				# logging.info("dest_path: %s" % event.dest_path)

			target_path = event.src_path
			if hasattr(event, "dest_path"):
				target_path = event.dest_path

			# logging.info("target_path: %s" % target_path)

			for asset in asset_folders:
				match = re.search(asset.get_abs_regex(), target_path)
				if match:
					# logging.info("-> %s" % asset.get_abs_regex())
					# logging.info(asset.glob)

					# try to update the cache
					if not self.cache.update(target_path):
						break


					if self.tools.has_key(asset.tool):
						tool = tools[asset.tool]
					else:
						raise UnknownToolException(
							"Unknown tool \"%s\"" % asset.tool
						)

					params = generate_params_for_file(
						self.settings.paths, 
						asset,
						target_path,
						self.platform
					)
					tool.execute(params)
					break

		def on_created(self, event):
			self.show_event(event)

		def on_deleted(self, event):
			self.show_event(event)

		def on_modified(self, event):
			self.show_event(event)

		def on_moved(self, event):
			self.show_event(event)

	logging.info("Monitoring assets in: %s..." % settings.paths.source_assets)

	event_handler = Apprentice(
		cache,
		settings,
		asset_folders,
		tools,
		platform
	)

	observer = Observer()
	observer.schedule(event_handler, settings.paths.source_assets, recursive=True)
	observer.start()

	import time
	import sys
	try:
		while True:
			time.sleep(1)
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
			logging.debug("Processing: \"%s\"" % search_path)
			
			if tools.has_key(asset.tool):
				tool = tools[asset.tool]
			else:
				raise UnknownToolException(
					"Unknown tool \"%s\"" % asset.tool
				)

			path_created = False

			for src_file_path in iglob(search_path):
				if not path_created:
					path_created = True
					# make all asset destination folders
					make_dirs(asset.abs_dst_folder)

				total_files += 1

				# try to update the cache
				if not cache.update(src_file_path):
					continue

				modified_files += 1

				params = generate_params_for_file(
					settings.paths, 
					asset,
					src_file_path,
					platform
				)
				tool.execute(params)

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
		"-m",
		"--monitor",
		dest="monitor",
		action="store_true",
		help="Monitor directories for changes and execute tools"
	)

	args = p.parse_args()

	# initialize logging
	logging.basicConfig(level=logging.INFO)

	# load config
	config = load_config(args.config_path)

	if not args.platform:
		args.platform = get_platform()
		logging.info("Host Platform is \"%s\"" % args.platform)

	# load tools
	config.tools = load_tools(args.config_path, getattr(config, "tools", None))

	# get cache path
	cache = Cache(args.config_path, remove=args.clear_cache)	
	cache.load()

	# conform all paths
	if getattr(config, "paths", None):
		base_path = os.path.dirname(os.path.abspath(args.config_path))
		config.paths = normalize_paths(base_path, config.paths)
		setattr(settings, "paths", AttributeStore(config.paths))

	# setup environment variables, path, etc.
	setup_environment(config.paths)
	
	# parse all tools
	if type(config.tools) == dict:
		for name in config.tools:
			tool = Tool(name=name, data=config.tools[name])
			tools[name] = tool
	else:
		for name, data in config.tools:
			tool = Tool(name=name, data=data)
			tools[name] = tool
	logging.info("Loaded %i tools." % len(tools.items()))

	# add internal tools
	tools["copy"] = CopyCommand(name="copy", data={})

	# parse asset folders
	for asset_glob in config.assets:
		data = dict(
			{u"glob" : asset_glob}.items() +
			config.assets[asset_glob].items()
		)
		asset_folder = AssetFolderMask(**data)
		asset_folder.make_folders_absolute(
			settings.paths.source_assets, 
			settings.paths.compiled_assets
		)
		asset_folders.append(asset_folder)
	logging.info("Loaded %i asset folders." % len(asset_folders))

	if args.monitor:
		# run monitoring
		monitor_assets(
			cache,
			settings,
			asset_folders,
			tools,
			args.platform
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
	main()