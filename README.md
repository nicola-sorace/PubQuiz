# PubQuiz
This is a simple web "pub quiz" interface written using the Python Flask interface.


### WARNING:
This code was not written with the intent of being scalable or extensible. All the logic is in a single Python file and fundamentally does not support multiple concurrent games. Database queries are done using SQLite, the interface uses basic Javascript (no JQuery) and there are virtually no comments in the code. Although there was an attempt at basic security, this web service is likely riddled with critical vulnerabilities and should NOT be hosted publicly.
