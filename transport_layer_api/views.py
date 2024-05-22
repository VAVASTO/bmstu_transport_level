from django.shortcuts import render
from django.http import HttpResponse
from rest_framework.decorators import api_view
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.errors import KafkaError
import requests
from drf_yasg import openapi

from django.shortcuts import render
from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework import status
from kafka import KafkaProducer
from itertools import islice
import threading
import time
import json

# kafka-console-consumer --bootstrap-server localhost:29092 --topic Messages --from-beginning
# kafka-console-consumer --bootstrap-server localhost:29092 --delete --topic Messages
# kafka-topics --bootstrap-server localhost:29092 --delete --topic Messages

byte_size = 130

topic = "Messages"

producer = KafkaProducer(
        bootstrap_servers=['localhost:29092'],
        value_serializer=lambda x: json.dumps(x).encode('utf-8'),
        batch_size=1
    )

def batched(iterable, n):
    it = iter(iterable)
    while batch := tuple(islice(it, n)):
        yield batch

@api_view(['POST'])
def post_segment(request):
    """
        Положить сегмент в брокер сообщений Kafka
    """
    producer.send(topic, request.data)

    return HttpResponse(status=200)

@api_view(['POST'])
def transfer_msg(request):
    """
        Разбить сообщение на сегменты длинной 130 байт и последовательная передача их на канальный уровень 
    """
    message = request.data['message']

    result_dicts = []
    request_message_bytes = bytes(message.encode('utf-8'))
    
    for i, batch in enumerate(batched(request_message_bytes, byte_size)):
        result_dicts.append(
            {
                "login": request.data['sender'],
                "timestamp": request.data['timestamp'],
                "part_message_id": i,
                "message": str(bytes(batch)),
            }
        )

    total_len = len(result_dicts)
    for d in result_dicts:
        d["amount_segments"] = total_len
        d["part_message_id"] = total_len - d["part_message_id"] - 1
        requests.post('http://25.59.51.201:8889/code/', json=d)
            
    return Response(status=status.HTTP_200_OK)

def send_mesg_to_app_layer(time, sender, message, flag_error):

    json_data = {
        "timestamp": time,
        "sender": sender,
        "message": message,
        "flag_error": flag_error
    } 
    print(f"передача сообщения на прикладной уровень {json_data}")

    return 0

def read_messages_from_kafka(consumer):
    message_recieved = []
    while True:
        messages = consumer.poll(2000)
        for tp, batch in messages.items():
            for message in batch:
                message_str = message.value
                if (not len(message_recieved) or message_recieved[-1]['timestamp'] == message_str['timestamp']):
                    message_recieved.append(message_str)
                    if (message_str['part_message_id'] == 0):
                        if (message_str['amount_segments'] == len(message_recieved)):
                            sorted_message = sorted(message_recieved, key=lambda x: x['part_message_id'], reverse=True)
                            msg = ""
                            for i in range(len(sorted_message)):
                                msg += sorted_message[i]['message']

                            send_mesg_to_app_layer(message_str['timestamp'], message_str['sender'], msg, 0)
                        else:
                            send_mesg_to_app_layer(message_str['timestamp'], message_str['sender'], "Error", 1)
                        message_recieved = []
                else:
                    send_mesg_to_app_layer(message_recieved[-1]['timestamp'], message_recieved[-1]['sender'], "Error", 1)
                    message_recieved = []
                    message_recieved.append(message_str)
                    print("Lost segment")
        time.sleep(2)

            

consumer = KafkaConsumer(
        topic,
        bootstrap_servers=['localhost:29092'],
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        group_id='test',
        auto_offset_reset='earliest',
        enable_auto_commit=True
    )

consumer_thread = threading.Thread(target=read_messages_from_kafka, args=(consumer,))

consumer_thread.start()
