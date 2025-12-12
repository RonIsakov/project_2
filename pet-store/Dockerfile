FROM python:alpine3.17
WORKDIR /app
COPY pet_store.py .
RUN pip install Flask requests pymongo
ENV FLASK_APP=pet_store.py
ENV FLASK_RUN_PORT=8000
ENV NINJA_API_KEY=NIJlfCOvSS0QcDN9iz/6ew==mV1vAh5dyTC9FP5r
EXPOSE 8000
CMD ["python", "pet_store.py"]
