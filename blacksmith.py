import os
import json
import platform
import shlex
import subprocess
import shutil
import re
import argparse
import logging
from glob import iglob

def makeDirsNoExcept( target_path, chmod=0775 ):
	try:
		os.makedirs( target_path, chmod )
	except:
		pass

def stripTrailingSlash( path ):
	if path[-1] == '/' or path[-1] == '\\':
		path = path[:-1]
	return path

def util_cleanPath( path ):
	path = stripTrailingSlash( path )
	return os.path.normpath( os.path.abspath(path) )

def get_platform():
	p = platform.platform().lower()
	#print( "Platform: " + p )
	if 'linux' in p:
		return "linux"
	elif "darwin" in p:
		return "macosx"	
	elif "nt" or "windows" in p:
		return "windows"
	else:
		return "unknown"

def runAsShell():
	is_shell = False
	if get_platform() == "windows":
		is_shell = True
	return is_shell

def loadConfig(path):
	file = open( path, "rb" )
	cfg = json.load( file )
	file.close()
	return AttributeStore( cfg )

def setupEnvironment( paths ):
	# add asset_path to PATH environment var
	if type(paths['tool_path']) is unicode:
		paths['tool_path'] = [ paths['tool_path'] ]

	tool_paths = ':'.join( paths['tool_path'] )

	os.environ['PATH'] = os.environ['PATH'] + ':' + tool_paths

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




class Tool(object):
	def __init__(self, *args, **kwargs):
		self.name = kwargs.get( 'name', 'Unknown' )
		self.commands = kwargs.get( 'commands', [] )

	def __str__(self):
		return 'Tool [Name=%s, Commands=%i]' % (self.name, len(self.commands))

	def execute( self, params ):
		for raw_cmd in self.commands:
			try:
				cmd = (raw_cmd % params).encode('ascii')
			except TypeError as e:
				logging.error( raw_cmd )
				logging.error( params )

			#logging.debug( cmd )
			runnable = shlex.split( cmd )

			try:			
				returncode = subprocess.call( runnable, shell=runAsShell() )
				if returncode != 0:
					logging.error( "ERROR %s" % cmd )
			except OSError as e:
				logging.error( "ERROR executing '%s', %s" % (cmd, e) )

class AssetFolder(object):
	def __init__(self, *args, **kwargs):
		self.glob = kwargs.get( 'glob', None )
		self.src_folder, self.glob = self.glob.split('/')
		self.dst_folder = kwargs.get( 'destination', self.src_folder )
		self.tool = kwargs.get( 'tool', None )
		self.params = kwargs.get( 'params', {} )

	def makeFoldersAbsolute( self, asset_source_path, asset_destination_path ):
		self.abs_src_folder = os.path.join( asset_source_path, self.src_folder )
		self.abs_dst_folder = os.path.join( asset_destination_path, self.dst_folder )

class UnknownToolException(Exception):
	pass

def generateParamsForFile( paths, asset, src_file_path ):
	# base parameters are from the asset block
	params = asset.params

	basename = os.path.basename(src_file_path)

	# default parameters
	params['src_file_path'] = src_file_path
	params['src_file_ext'] = os.path.basename(src_file_path).split('.')[1]
	params['dst_file_path'] = os.path.join( paths.compiled_assets, asset.dst_folder, basename )
	params['dst_file_noext'] = os.path.join( paths.compiled_assets, asset.dst_folder, basename.split('.')[0] )
	

	# setup commands - this needs to be moved to an external .conf
	cmd_move = ''
	if get_platform() == 'windows':
		cmd_move = 'move'
	else:
		cmd_move = 'mv'

	params['cmd_move'] = cmd_move

	return params


class CopyCommand(Tool):
	def execute( self, params ):
		try:
			#logging.debug( "[COPY] %s -> %s" % (params['src_file_path'], params['dst_file_path']) )
			shutil.copyfile( params['src_file_path'], params['dst_file_path'] )
		except IOError as e:
			logging.info( 'IOError: %s' % e )

def main():
	commands = {}
	config = None
	ignore_list = []
	settings = AttributeStore()
	tools = {}
	asset_folders = []
	log_levels = {
		'debug' : logging.DEBUG,
		'info' : logging.INFO,
		'warn' : logging.WARN,
		'error' : logging.ERROR
	}
	
	p = argparse.ArgumentParser()
	p.add_argument( '-c', '--config', dest='config_path', metavar='CONFIG_FILE_PATH', help = 'Path to configuration file to use when converting assets', required=True )
	p.add_argument( '-l', '--loglevel', dest='log_level' )
	args = p.parse_args()

	# load config
	if os.path.exists( args.config_path ):
		config = loadConfig( args.config_path )

	# sort out the log level (there is probably a better way to do this?)
	if args.log_level == None:
		args.log_level = 'info'
	if args.log_level not in log_levels:
		logging.error( 'Unknown log level: %s' % args.log_level )
	logging.basicConfig( level=log_levels[ args.log_level ] )

	# conform all paths
	if getattr(config, 'paths', None):
		for path in config.paths:
			key = path
			if type(config.paths[key]) is unicode:
				value = util_cleanPath( config.paths[key] )
			elif type(config.paths[key]) is list:
				path_list = config.paths[key]
				for path in path_list:
					path = util_cleanPath( path )
				value = path_list
			else:
				raise Exception('Unknown path type! %s' % type(config.paths[key]) )
			
			#logging.info( "* %s -> %s" % (key, value) )
			config.paths[ key ] = value

		setattr(settings, 'paths', AttributeStore( config.paths ) )

	# setup environment variables, path, etc.
	setupEnvironment( config.paths )
	
	# parse all tools
	for name in config.tools:
		tool = Tool( name=name, commands=config.tools[name] )
		tools[ name ] = tool
	logging.info( "Loaded %i tools." % len(tools.items()) )

	# add internal tools
	tools[ 'copy' ] = CopyCommand(name='copy')

	# parse asset folders
	for asset_glob in config.assets:
		data = dict({u'glob' : asset_glob}.items() + config.assets[asset_glob].items())
		asset_folder = AssetFolder( **data )
		asset_folder.makeFoldersAbsolute( settings.paths.source_assets, settings.paths.compiled_assets )
		asset_folders.append( asset_folder )
	logging.info( "Loaded %i asset folders." % len(asset_folders) )

	# loop through each asset path and glob
	# run the tool associated with each file
	logging.info( "Running tools on assets..." )
	for asset in asset_folders:
		try:
			search_path = os.path.join(asset.abs_src_folder, asset.glob)
			logging.debug( "Processing: '%s'" % search_path )
			
			if tools.has_key( asset.tool ):
				tool = tools[ asset.tool ]
			else:
				raise UnknownToolException( 'Unknown tool "%s"' % asset.tool )

			# make all asset destination folders
			makeDirsNoExcept( asset.abs_dst_folder )

			for src_file_path in iglob( search_path ):
				#logging.info( "-> %s" % src_file_path )
				params = generateParamsForFile( settings.paths, asset, src_file_path )
				tool.execute( params )
		except UnknownToolException as e:
			logging.warn( e.message )
			continue

	logging.info( "Complete." )
if __name__ == "__main__":
	main()