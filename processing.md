# How OpenMates works

By starting OpenMates via Docker, it will start a FastAPI server and RabbitMQ server.
Then, whenever a message is posted to the FastAPI server, it will be processed and a response sent back.