FROM python

RUN mkdir -p /application
RUN cd /application
COPY . /application

RUN pip3 install flask
RUN pip3 install boto3

CMD ["python3", "/application/autograder.py"]