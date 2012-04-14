#!/usr/bin/env python
# This is the voice control system for linux.
# All it does is take commands given to it from CMU sphinx and
# run the corresponding scripts from a directory.
#
# The speech recognition code is based off of the example from
# CMU sphinx. The remainder of the code was created by
# Spencer Julian. The relevant bits are available under the
# GPL, the remainder under CMU Sphinx's license.
#
# Last update: April 11, 2012.

import pygtk 
pygtk.require('2.0') 
import gtk 

import pygst, gobject
pygst.require('0.10')
import gst,os,sys,string,re,time
from urllib2 import urlopen
from subprocess import call

FullDictionary = "https://cmusphinx.svn.sourceforge.net/svnroot/cmusphinx/trunk/cmudict/cmudict.0.7a"

class Error(Exception):
	pass
class DownloadError(Error):
	def __init__(self, words, msg):
		self.word = words
		self.mst = msg
	def __str__(self, words, msg):
		return repr(words)

class Sphinx(object):
	def __init__(self, lang, config):
		"""Initialize the CMU Sphinx system"""
		self.init_gui()
		self.config = config
		self.init_gst(lang)

	def init_gui(self):
		"""Initialize the GUI components"""
		self.window = gtk.Window()
		self.window.connect("delete-event", gtk.main_quit)
		self.window.set_default_size(400,200)
		self.window.set_border_width(10)
		vbox = gtk.VBox()
		self.textbuf = gtk.TextBuffer()
		self.text = gtk.TextView(self.textbuf)
		self.text.set_wrap_mode(gtk.WRAP_WORD)
		vbox.pack_start(self.text)
		self.window.add(vbox)
		self.window.show_all()

	def init_gst(self, lang):
		"""Initialize the speech components"""
		self.pipeline = gst.parse_launch('gconfaudiosrc ! audioconvert ! audioresample ! vader name=vad auto-threshold=true ! pocketsphinx name=asr ! fakesink')
		asr = self.pipeline.get_by_name('asr')
		asr.connect('result', self.asr_result)
		asr.set_property('configured', True)
		asr.set_property('lm', lang + '.lm')
		asr.set_property('dict',lang + ".dict")

		bus = self.pipeline.get_bus()
		bus.add_signal_watch()
		bus.connect('message::application', self.application_message)

		self.pipeline.set_state(gst.STATE_PLAYING)

	def asr_result(self, asr, text, uttid):
		"""Forward result signals on the bus to the main thread."""
		struct = gst.Structure('result')
		struct.set_value('hyp', text)
		struct.set_value('uttid', uttid)
		asr.post_message(gst.message_new_application(asr, struct))

	def application_message(self, bus, msg):
		"""Receive application messages from the bus."""
		msgtype = msg.structure.get_name()
		self.final_result(msg.structure['hyp'], msg.structure['uttid'])

	def final_result(self, hyp, uttid):
		self.textbuf.begin_user_action()
		self.textbuf.delete_selection(True, self.text.get_editable())
		self.textbuf.insert_at_cursor(hyp)
		Processes().forkProcess(self.config, hyp)
		self.textbuf.end_user_action()

	def set_running(self, run):
		if(run):
			self.pipeline.set_state(gst.STATE_PLAYING)
			vader = self.pipeline.get_by_name('vad')
			vader.set_property('silent', False)
		else:
			vader = self.pipeline.get_by_name('vad')
			vader.set_property('silent', True)

class Processes():
	def forkProcess(self, commands, action):
		try:
			run=commands[action]
			if (run == "%exit%"):
				print "It's been fun! Closing."
				gtk.main_quit()
			else:
				self.runProcess("./scripts/" + run)
				return run
		except KeyError:
			print "Could not recognize what you said..."
			return None

	def runProcess(self, run):
		try:
			pid = os.fork()
		except OSError, e:
			raise RuntimeError("Could not fork. %s %d" % (e.strerror, e.errno))
		if pid == 0:
			os.execv(run, [""])

class FileIO():
	def readConfig(self, filename):
		#readConfig reads a configuration file and spits out a dictionary
		#of {voice command, script} values.
		commands = {}
		f = open(filename,'r')
		for line in f.readlines():
			commands[line.split('=')[0]] = line.split('=')[1].strip()
		f.close()
		return commands

	def checkDictionary(self, commands, dictionary):
		fd = open(dictionary, 'r')
		voice = []
		words = []
		for line in fd.readlines():
			voice.append(re.sub('\(\)', '', re.sub('[0-9]+', '', line.split()[0])))
		fd.close()
		for key in commands:
			for word in key.upper().split(" "):
				words.append(word)
		voiceSet = set(voice)
		wordSet = set(words)
		if (len(wordSet) != len(voiceSet)):
			return wordSet.difference(voiceSet)
		else:
			return None

	def generateDictionary(self, commands, outDict, outLM, newList=None):
		#generate Dictionary takes a dictionary of {voice command, script}
		#values and generates a pocket sphinx dictionary and language
		#model off of that, by pulling the appropriate lines from
		#the CMU sphinx sourceforge page.
		words = []
		outputDictionary = []
		outputModel = []

		if (newList == None):
			for key in commands:
				for word in key.upper().split(" "):
					words.append(word)
			wordSet = set(words)
		else:
			for item in newList:
				for word in item.upper().split(" "):
					words.append(word)
			wordSet = set(words)

		fullList = urlopen(FullDictionary)
		for line in fullList:
			testLine = re.sub('\(\)', '', re.sub('[0-9]+', '', line))
			if (wordSet.intersection(set(testLine.split())) != set()):
				modLine = line.split(None, 1)
				modLine[1] = re.sub('[0-9]+', '', modLine[1])
				outputDictionary.append(" ".join(modLine))
		if len(outputDictionary) < len(wordSet):
			output = wordSet.difference(set(outputDictionary))
			raise DownloadError(output, "These words could not be found in the full list. Please generate these words manually. ")
		
		if (newList == None):
			fd = open(outDict, 'w')
		else:
			fd = open(outDict, 'a')
		fd.write("".join(outputDictionary))
		fd.close

		if (newList == None):
			#Generate the language model.
			outputModel.append("\\data\\\nngram 1=")
			outputModel.append(str(len(wordSet) + 2))
			outputModel.append("\nngram 2=")
			outputModel.append(str(len(wordSet)*2))
			outputModel.append("\nngram 3=")
			outputModel.append(str(len(wordSet)))
			
			#one grams:
			outputModel.append("\n\n\\1-grams:\n-0.7782 </s> -0.3010\n-0.7782 <s> -0.2218\n")
			for word in words:
				outputModel.append("-1.9243 ")
				outputModel.append(word)
				outputModel.append(" -0.2218\n")
			#two grams:
			outputModel.append("\n\\2-grams:\n")
			for word in words:
				outputModel.append("-1.4472 <s> ")
				outputModel.append(word)
				outputModel.append(" 0.0000\n")
			for word in words:
				outputModel.append("-0.3010 ")
				outputModel.append(word)
				outputModel.append(" </s> -0.3010\n")
			#three grams:
			outputModel.append("\n\\3-grams:\n")
			for word in words:
				outputModel.append("-0.3010 <s> ")
				outputModel.append(word)
				outputModel.append(" </s>\n")
			outputModel.append("\n\\end\\")
		else:
			fm = open(outLM, 'r')
			group = 0
			for line in fm.readlines():
				if (group == 0):
					if(line.split('=')[0] == "ngram 1"):
						outputModel.append("ngram 1=")
						outputModel.append(str(int(line.split('=')[1]) + len(wordSet)))
						outputModel.append("\n")
					elif(line.split('=')[0] == "ngram 2"):
						outputModel.append("ngram 2=")
						outputModel.append(str(int(line.split('=')[1]) + (len(wordSet)*2)))
						outputModel.append("\n")
					elif(line.split('=')[0] == "ngram 3"):
						outputModel.append("ngram 3=")
						outputModel.append(str(int(line.split('=')[1]) + len(wordSet)))
						outputModel.append("\n")
					elif(line == "\\1-grams:\n"):
						group = 1;
						outputModel.append(line)
					else:
						outputModel.append(line)
				elif (group == 1):
					if(line == "\n"):
						for word in words:
							outputModel.append("-1.9243 ")
							outputModel.append(word)
							outputModel.append(" -0.2218\n")
						group = 2;
					outputModel.append(line)
				elif (group == 2):
					if(line.split()[0] == "-0.3010"):
						for word in words:
							outputModel.append("-1.4472 <s> ")
							outputModel.append(word)
							outputModel.append(" 0.0000\n")
						group = 3
					outputModel.append(line)
				elif(group == 3):
					if(line == "\n"):
						for word in words:
							outputModel.append("-0.3010 ")
							outputModel.append(word)
							outputModel.append(" </s> -0.3010\n")
						group = 4
					outputModel.append(line)
				elif (group == 4):
					if(line == "\n"):
						for word in words:
							outputModel.append("-0.3010 <s> ")
							outputModel.append(word)
							outputModel.append(" </s>\n")
						group = 5
					outputModel.append(line)
				else:
					outputModel.append(line)
			fm.close()

		fm = open(outLM, 'w')
		fm.write(''.join(outputModel))
		fm.close()

if __name__ == "__main__":
	if (len(sys.argv) >= 1):
		fio = FileIO()
		if(set(sys.argv).intersection(set(["-d", "-D", "--download", "--redownload"]))):
			if (len(sys.argv) >= 4):
				print "Generating new dictionary file, " + sys.argv[len(sys.argv)-1] + ".dict and new language model " + sys.argv[len(sys.argv)-1] + ".lm."
				config = fio.readConfig(sys.argv[len(sys.argv)-2])
				fio.generateDictionary(config, sys.argv[len(sys.argv)-1] + ".dict", sys.argv[len(sys.argv)-1] + ".lm")
				print "Generation complete. Exiting."
				quit()
			else:
				print "Incorrect number of arguments."
				quit()
		elif(set(sys.argv).intersection(set(["-h", "-H", "--help"]))):
			print "No help yet! Still working on stuff."
			quit()
		elif(len(sys.argv) == 3):
			config = fio.readConfig(sys.argv[len(sys.argv)-2])
			if (os.path.exists(sys.argv[len(sys.argv)-1] + ".dict")):
				newCommands = fio.checkDictionary(config, sys.argv[len(sys.argv)-1] + ".dict")
				if (newCommands):
					fio.generateDictionary(config, sys.argv[len(sys.argv)-1] + ".dict", sys.argv[len(sys.argv)-1] + ".lm", newCommands)
			else:
				fio.generateDictionary(config, sys.argv[len(sys.argv)-1] + ".dict", sys.argv[len(sys.argv)-1] + ".lm")
			#Supress ALL THE OUTPUT.
			test = Sphinx(sys.argv[len(sys.argv)-1], config)
			gtk.main()
		else:
			print "Error with your arguments!"
			quit()
