import os
import json

import argparse
from glob import iglob
import logging
import re
import time

#import watchdog
#from watchdog.events import FileSystemEventHandler, LoggingEventHandler
#from watchdog.observers import Observer


from models import (
	AssetFolder,
	AttributeStore,
	Cache,
	CopyCommand,
	Tool,
	UnknownToolException
)

from util import(
	clean_path,
	generate_params_for_file,
	get_platform,
	load_tools,
	make_dirs,
	run_as_shell,
	setup_environment,
	strip_trailing_slash,
	type_is_string
)



# class Apprentice(watchdog.events.FileSystemEventHandler):
# 	"""
# 		The apprentice will help us out by monitoring the paths we
# 		are interested in.
# 	"""

# 	def show_event(self, event):
# 		logging.info("event_type: %s" % event.event_type)
# 		logging.info("is_directory: %s" % event.is_directory)
# 		logging.info("src_path: %s" % event.src_path)

# 		if hasattr(event, "dest_path"):
# 			logging.info("dest_path: %s" % event.dest_path)

# 	def on_created(self, event):
# 		self.show_event(event)

# 	def on_deleted(self, event):
# 		self.show_event(event)

# 	def on_modified(self, event):
# 		self.show_event(event)

# 	def on_moved(self, event):
# 		self.show_event(event)






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


def main():
	commands = {}
	config = None
	ignore_list = []
	settings = AttributeStore()
	tools = {}
	asset_folders = []

	log_levels = {
		"debug" : logging.DEBUG,
		"info" : logging.INFO,
		"warn" : logging.WARN,
		"error" : logging.ERROR
	}
	
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
		"-l",
		"--loglevel",
		dest="log_level"
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

	# sort out the log level
	if args.log_level == None:
		args.log_level = "info"
	if args.log_level not in log_levels:
		logging.error("Unknown log level: %s" % args.log_level)

	# initialize logging
	logging.basicConfig(level=log_levels[args.log_level])

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

		for key in config.paths:
			if type_is_string(config.paths[key]):
				value = clean_path(config.paths[key])
				value = os.path.abspath(os.path.join(base_path, value))
			elif type(config.paths[key]) is list:
				path_list = config.paths[key]
				for path in path_list:
					path = clean_path(path)
					path = os.path.abspath(os.path.join(base_path,path))
				value = path_list
			else:
				raise Exception(
					"Unknown path type! key: %s -> %s" %
					(key, type(config.paths[key]))
				)
			
			config.paths[key] = value

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
		asset_folder = AssetFolder(**data)
		asset_folder.make_folders_absolute(
			settings.paths.source_assets, 
			settings.paths.compiled_assets
		)
		asset_folders.append(asset_folder)
	logging.info("Loaded %i asset folders." % len(asset_folders))

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
					args.platform
				)
				tool.execute(params)

		except UnknownToolException as e:
			logging.warn(e.message)
			continue

	# write cache to file
	cache.save()

	logging.info("Complete.")
	logging.info("Modified / Total - %i/%i" % (modified_files, total_files))


# def monitor_test():
# 	logging.basicConfig(level=logging.INFO)
	

# 	event_handler = Apprentice()
# 	observer = Observer()
# 	observer.schedule(event_handler, "/Users/apetrone/Documents/gemini/assets", recursive=True)
# 	observer.start()

# 	import time
# 	import sys
# 	try:
# 		while True:
# 			time.sleep(1)
# 	except KeyboardInterrupt:
# 		observer.stop()

# 	observer.join()	

if __name__ == "__main__":
	main()
		
	#monitor_test()