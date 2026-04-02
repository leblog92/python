import pyttsx3
engine = pyttsx3.init()
voices = engine.getProperty('voices')
engine.setProperty('rate', 130)
for voice in voices:
   engine.setProperty('voice', voice.id)
   engine.say('Le vif zéphyr jubile sur les kumquats du clown gracieux.')
engine.runAndWait()