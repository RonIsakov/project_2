FROM python:alpine3.17
WORKDIR /app
RUN pip install Flask requests pymongo
ENV FLASK_APP=pet_order.py
ENV FLASK_RUN_PORT=8080
COPY pet_order.py .
EXPOSE 8080
CMD ["python", "pet_order.py"]
