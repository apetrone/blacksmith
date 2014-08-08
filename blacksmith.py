import os
import json

import argparse
from glob import iglob
import logging
import re
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from models import (
	AssetFolder,
	AttributeStore,
	CopyCommand,
	Tool,
	UnknownToolException
)

from util import(
	clean_path,
	generate_params_for_file,
	get_platform,
	make_dirs,
	run_as_shell,
	setup_environment,
	source_file_cache_status,
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


def update_cache(path, cache):
	cache[path] = os.path.getmtime(path)

def main():
	commands = {}
	config = None
	ignore_list = []
	settings = AttributeStore()
	tools = {}
	asset_folders = []
	cache = {}
	alter_code = {0: "A", 1:"M", 2:"O"}
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
		logging.info("Platform defaulting to: %s" % args.platform)

	# attempt to load the tools via the tool path
	if config.tools and type_is_string(config.tools):
		base_path = os.path.dirname(args.config_path)
		#logging.info( "base_path = %s" % base_path )
		#logging.info( "config.tools = %s" % config.tools )
		abs_tools_path = os.path.abspath(
			os.path.join(base_path, config.tools)
		)
		logging.info("Importing tools from %s..." % abs_tools_path)
		config.tools = load_config(abs_tools_path)

	# load cache
	cache_path = os.path.splitext(args.config_path)[0] + ".cache"

	if args.clear_cache and os.path.exists(cache_path):
		logging.info("clearing cache at %s" % cache_path)
		os.unlink(cache_path)
	
	if os.path.exists(cache_path):
		logging.info("Reading cache from %s..." % cache_path)
		file = open(cache_path, "rb")
		cache = json.load(file)
		file.close()
	elif not args.clear_cache:
		logging.warn("No cache at %s" % cache_path)

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
			
			if tools.has_key( asset.tool ):
				tool = tools[ asset.tool ]
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

				cache_status = source_file_cache_status(
					src_file_path,
					cache
				)
				if cache_status == 2:
					continue

				logging.info(
					"%c -> %s" %
				 	(alter_code[cache_status], src_file_path)
				)
				modified_files += 1

				# make sure we update the file cache
				update_cache(src_file_path, cache)

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
	logging.info("Writing cache %s..." % cache_path)
	file = open(cache_path, "wb")
	file.write(json.dumps(cache, indent=4))
	file.close()

	logging.info("Complete.")
	logging.info("Modified / Total - %i/%i" % (modified_files, total_files))

if __name__ == "__main__":
	main()
