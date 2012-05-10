# About

I created this to solve the problem where I wanted to automate converting source assets into
platform-specific formats.

For example, I can compress WAV sounds to OGG for use on Desktop machines. However, decoding these on the fly introduces too much overhead for iOS devices. Thus, I want them to use a hardware accelerated format.
I don't want to manually keep track and convert these files because that is error prone and time consuming.

The solution is to have a script process everything and put it in the correct place automatically.

# Usage

Write an assetconfig file and then point blacksmith to it.
You specify asset directories relative to the source_assets folder. In doing so, you also provide a wild card to match files. For each file in this directory that matches the wild card, a 'tool' will be executed on that file.

# Asset Config Files

An asset config file is divided into three sections. Paths, Tools, and Assets.

## Paths
There are three paths that are required when writing this file.
source_assets - root where the source assets can be found.
compiled_assets - root where the 'final' version of the files will be placed
tool_path - This can be a single string or list of strings to append to the PATH environment variable when executing tools

## Tools
This is a dictionary of tools. Each tool is defined by name to have a list of commands that are executed (as if they were a batch or shell script).
Here's a contrived example of creating a 'tool' out of the unix cp command.

	'cp': # the name can be anything, but is used to reference the tool from the Assets section.
	[
		"cp -r %(src_file_path) %(dst_file_path)"
	]

This is now a tool called 'cp', which will copy each file to the destination. Note: In this example, this command will fail on Windows because there is no 'cp' command by default. Use of the built-in 'copy' tool is recommended.

A list of default parameters are accessible for each tool:
	src_file_path - absolute path to source file
	src_file_ext - source file's extension
	dst_file_path - absolute path to destination file (assumes same name as source)
	dst_file_noext - absolute path to destination file, with no extension

This takes advantage of Python's Dictionary-based string formatting.

At the moment, there is only one built-in tool, "copy". This copies a file from the source to the destination in a cross-platform manner (using python's shutil).

## Assets
The "key" in this section, should be a relative-folder name with wild card matching pattern.
If your source_assets folder had a folder called "textures" and you only wanted to operate on PNG files in that folder, you would specify this as follows:

	"textures/*.png" :
	{
		...
	}

You can specify key-value parameters for each asset which are in turn passed to the tool.
In order to pass these along to the tool, they must be defined in a 'params' block. Here's an example:
Assuming this is an assets entry:

	"fonts/*.ttf":
	{
		"tool" : "fonttool",
		"params" :
		{
			"point_size" : 12,
			"antialiased" : 0
		}
	}

You can have a tool called "fonttool" that makes use of these parameters as follows:

	"fonttool":
	{
		"ftool -i %(src_file_path) %o (%dst_file_noext)s.font -s %(point_size)d -a %(antialiased)d"
	}
	
Also worth noting is that you can change the destination folder name. I keep platform specific files in folders called: "textures.desktop", or "shaders.ios" which I then rename with the asset config to "textures" and "shaders" respectively. This keeps my final resource names uniform, while keeping the source files separate.


## Example Asset Config file
	{
		"paths":
		{
			"compiled_assets" : "build",
			"source_assets" : "assets",
			"tool_path" : "tools/bin"
		},

		"tools" :
		{
			"sox" :
			[
				"sox -t%(src_file_ext)s %(src_file_path)s %(dst_file_noext)s.%(platform_extension)s"
			]
		},

		"assets":
		{
			"shaders.desktop/*.vert":
			{
				"tool" : "copy",
				"destination" : "shaders"
			},
			"shaders.desktop/*.frag":
			{
				"tool" : "copy",
				"destination" : "shaders"
			},
			"sounds/*.wav":
			{
				"tool" : "sox",
				"params":
				{
					"platform_extension" : "ogg"
				}
			}
		}
	}

# Roadmap

- Add a mode to facilitate directory watching (perhaps with watchdog?) such that you can leave this running while working and it will automatically pickup and convert any changes for you.
- Implement a caching mechanism such that only newly modified files will be converted each run.
- Improve support for cross-platform tools or commands. In this context, commands could be used by tools.
