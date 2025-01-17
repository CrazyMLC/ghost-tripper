#!/usr/bin/env python3
from io import BytesIO
from struct import unpack
from pathlib import Path
import sys,os,time,argparse,fnmatch

from lib.tables import *
from lib.message import *
from lib.lz11 import *

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description = "Decodes 1LMG files into plaintext.")
	parser.add_argument("-i", "--input", help="Input files or folder, output must be a folder for multiple files", nargs='*')
	parser.add_argument("-o", "--output", help="Output file or folder", default=os.path.join(".","decoded",""))
	parser.add_argument("-e", "--error", help="Error file")
	parser.add_argument("-w", "--wildcard", help="Filters folder contents using fnmatch")
	parser.add_argument("-c", "--compress", help="Controls compression. 1 is never, and 2 decompresses when needed", action='count', default=2)
	parser.add_argument("-f", "--folder", help="Disables keeping folder structure", action='store_false')
	parser.add_argument("-s", "--silent", help="Skip prints", action='store_true')
	parser.add_argument("-v", "--verbose", help="Wait for confirm", action='store_true')
	parser.add_argument("dragged", help="Catches dragged and dropped files", nargs='*')



def decode_1LMG(loadpath, savepath=None, compress=2):
	"""Open and decode a 1LMG file at the given filepath and print it, or save it if given a savepath."""
	with open(loadpath, 'rb') as file:
		data = file.read()
		
	# Time to check if it's a valid file, or decompress it if it's still compressed.
	if data[:4] != b'1LMG':
		if data[5:9] == b'1LMG':
			if compress > 1:
				try:
					data = lz11_decompress(data)
				except:
					sys.stderr.write(f"lz11 decompression failed: {loadpath}\n")
					return -3
			else:
				sys.stderr.write(f"1LMG File is compressed: {loadpath}\n")
				return -1
		else:
			sys.stderr.write(f"File isn't 1LMG format: {loadpath}\n")
			return -1
	
	data = BytesIO(data)
	data.seek(4)
	# Let's find all the important file locations
	mystery, = unpack('<L', data.read(4))# Seems to have something to do with scripts...
	data_length, = unpack('<L', data.read(4))
	string_length, = unpack('<L', data.read(4))
	# Strings start directly after the data, and the header is always 0x34 long, so we can figure out where the strings are now.
	string_position = 0x34 + data_length
	# We know both the string position and length now, and the pointer table is right after.
	pointers_position = string_position + string_length
	
	# The first entry in the pointer table is always the number of messages. Let's go find that.
	data.seek(pointers_position)
	message_count, = unpack('<L', data.read(4))
	# If the message count is 0, our output file will be blank. Let's return an error instead.
	if message_count == 0:
		sys.stderr.write(f"1LMG is empty: {loadpath}\n")
		return -2
	
	# Well, we can find the pointer table length now. And that means we can get the position of the labels, too.
	pointers_length = 4+message_count*8
	labels_position = pointers_position + pointers_length
	
	
	# Alright. Now we know all the locations within the file, so let's start reading data.
	# We're already here, so let's read the pointer table.
	messages = []
	# Let's do the first one outside of the loop, it'll make it a bit cleaner.
	messages.append(
		Message( *unpack('<LL', data.read(8)) )
	)
	if message_count > 1:
		for m in range(1,message_count):
			messages.append(
				Message( *unpack('<LL', data.read(8)) )
			)
			# Scripts don't use stop codes necessarily, so we'll have to calculate lengths for the previous messages, one at a time.
			messages[m-1].length = messages[m].pointer - messages[m-1].pointer
	# And then calculate the last message's length.
	messages[-1].length = string_position - messages[-1].pointer


	# Now, let's get the data from the pointers we found.
	for message in messages:
		# We'll let the message class handle the data.
		message.get_label(data, labels_position)
		message.decode(data)
		
	# Sometimes the last message in a file will have a lingering 0x0000 in order to 4byte-align the pointer table.
	# Can't necessarily tell when it's part of the message or not, but we can easily cut it out for dialogue files.
	if string_length == 4:# Most if not all script files have a higher length, so we can use this to identify dialogue files.
		if messages[-1].decoded[-(1+len(commands[0xfffe])):] == commands[0xfffe]+'0':
			messages[-1].decoded = messages[-1].decoded[:-1]
	
	
	# We're done! Let's print each message using the message class's string conversion function.
	if savepath == None:
		print(*messages, sep='')
	else:# Or save it if given a path.
		with open(savepath, "w", encoding="utf-8") as text_file:
			for message in messages:
				text_file.write(str(message))
	
	# Currently ghost-treader doesn't support any 1LMG file with string data. We should report if we failed to losslessly decode the file because of that.
	if string_length == 4:
		return 0 # This means the file was successfully decoded.
	else:
		return 1 # Alternatively, this means the decode wasn't so successful. The decode is only partial, and meant for debugging/hacking purposes.


# Now for the console interface.
if __name__ == "__main__":
	args = parser.parse_args()
	
	def print_progress (iteration, total):
		"""Based on stack overflow 'Text Progress Bar in the Console [closed]'"""
		percent = "{0:.1f}".format(100 * (iteration / float(total)))
		filledLength = int(100 * iteration // total)
		bar = '█' * filledLength + '-' * (100 - filledLength)
		print(f'\r|{bar}| {percent}%', end = "\r")
		if iteration == total: 
			print()
	
	def end_program(message, help=False, wait=-1):
		print(message)
		if help:
			parser.print_help()
		if wait == -1:
			input("Press enter to exit")
		elif wait > 0:
			time.sleep(wait)
		quit()
		
	# Keep track of when the program started.
	if not args.silent:
		start = time.perf_counter()
	
	# Try to initalize lz11, and disable compress if it failed.
	if args.compress == 2 and not lz11_init():
		args.compress = 1
	
	# First and foremost, let's see if we have any inputs so we can actually run.
	if args.input == None:
		if args.dragged == []:
			end_program("ERROR: No inputs! Printing help text...", help=True)
		args.input = args.dragged
	# Let's keep track if there are multiple inputs, so we can throw an error if the output isn't a folder.
	multiple = len(args.input) > 1
	if not multiple and os.path.isdir(args.input[0]):
		multiple = True
	
	# Now to check the output.
	output_is_folder = False
	if args.output[-1] == os.sep or os.path.isdir(args.output):
		output_is_folder = True
		if not os.path.exists(args.output):# If the output is a folder and doesn't exist, let's make it for the user.
			try:
				os.mkdir(args.output)
			except:
				end_program("ERROR: Couldn't create output folder.")
	elif multiple:# If we have multiple inputs and the output isn't a folder, we should end execution.
		end_program('ERROR: Input was multiple files, but the output was a single file.')
	
	# Let's set up error reporting for errors that won't stop execution...
	if args.error != None:
		try:
			stderr_temp = sys.stderr
			sys.stderr = open(args.error,'a')
			sys.stderr.write(time.strftime(f'[%Y-%m-%d %H:%M:%S] {os.path.basename(__file__)}\n',time.localtime()))
		except:
			end_program(f"ERROR: Invalid error file.\n{args.error}")
	
	# Alright, let's filter through these inputs to get a list of filenames. Some of them may be folders.
	inputs = []
	for path in args.input:
		if not os.path.exists(path):
			end_program(f"ERROR: Input doesn't exist.\n{path}")
		if not os.path.isdir(path):
			inputs.append((path,os.path.basename(path)))
		else:# Time to sort through the folder...
			for root, dirs, files in os.walk(path):
				for name in files:
					if args.wildcard != None:
						if not fnmatch.fnmatch(os.path.basename(name), args.wildcard):
							continue
					inputs.append(
						(os.path.join(root,name),
						os.path.relpath(os.path.join(root,name),path))
						)
	# Get rid of any duplicate filepaths in the list, just in case...
	#inputs = list(dict.fromkeys(inputs))# Disabled for now
	
	# Good to go! Let's get through these files.
	decoded_files = 0
	for i,input in enumerate(inputs):
		if not args.silent:
			print_progress(1+i,len(inputs)+1)
			
		if output_is_folder:
			if args.folder:
				filename = input[1]
			else:
				filename = os.path.basename(input[1])
			savepath = os.path.join(args.output, filename)
		else:
			savepath = args.output
		
		# Pathlib is way better at this, so let's use it to create the folder structure.
		if args.folder:
			Path(savepath).parent.mkdir(parents=True, exist_ok=True)
		
		if decode_1LMG(input[0],savepath+".txt") >= 0:
			decoded_files += 1

	# Looks like we're done. Let's finish whatever outputs we have, and then exit.
	if not args.silent:
		print_progress(1,1)
	sys.stderr.flush()
	if args.error != None:
		sys.stderr = stderr_temp
	if not args.silent:
		end_program("\nSuccessfully decoded {0} file{1} in {2:.1f}ms".format(decoded_files,("" if (decoded_files==1) else "s"),(time.perf_counter()-start)*1000), wait=(-1 if args.verbose else 5))
