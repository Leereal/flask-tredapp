from flask import Flask     
from flask_cors import CORS
from database import db
from trader import Trader
from socket_manager import init_socket, socket
from bson import ObjectId
from threading import Thread
from iqoptionapi.stable_api import IQ_Option
from decouple import config
import asyncio


app = Flask(__name__)   # Flask constructor 
app.config['SECRET_KEY'] = 'secret!'
CORS(app) 
init_socket(app)

running_traders = [] 

def create_and_run_trader(email,token,risk_management, account_type):
    try:  
        trader = Trader(email, token,risk_management,account_type)        
        running_traders.append(trader)
    except Exception as e:
        print(f"Error creating and running trader: {e}")

@app.route('/')       
def index(): 
    return 'HELLO, HOW DID YOU GET HERE?'

@socket.on('handleBot')
def handle_start_bot(data):    
    id = data['id']
    activate = data['activate']

    if id and activate:      
        try:
            #Get all active connections for the current robot            
            connections_query = db.connections.find({'active':True, 'robot': ObjectId(id) })      
            robot_connections = [populate_connection(connection) for connection in connections_query]
            threads = []
            for document in robot_connections:
                risk_management = {                    
                    "maximum_risk_target": float(document["target_percentage"]),# is target_percentage # Balance you want to reach due to profit
                    "maximum_risk_": float(document["stop_loss"]),  # Balance you want to reach due to loss
                    "stake_percentage": float(document["stake_percentage"]),                   
                    "risk_type": str(document["risk_type"]),
                    "risk_percentage": float(document["risk_percentage"]),
                    "stake":float(document["stake"]), # This is the starting stake default
                    "expiration" : int(document["expiration"]),
                    "currency": str(document["currency"]),
                    "last_profit":float(document["last_profit"]),
                    "payout":float(document["payout"]),
                    "last_profit":float(document["last_profit"]),
                    "robot_connection_id":str(document["_id"]),
                    "robot_connection":document
                }
                thread = Thread(target=create_and_run_trader, args=(
                    document['account']['email'],
                    document['account']['token'],
                    risk_management,
                    document['account']['account_type']
                ))
                threads.append(thread)
                thread.start()                

            for thread in threads:
                    thread.join()
            # Run bots that are fully automated after all accounts activated
            if data['auto'] == True:
                for trader in running_traders:
                    symbols = trader.robot_connection['robot']['symbols']
                    for symbol in symbols:
                        if symbol['active']:
                            trader.run_automated_bot(symbol)
                                       
            
        except Exception as e:
            print(f"Error retrieving documents from MongoDB: {e}")
    elif id and not activate:
        #Logic to stop the bot with the same id

        #Delete all active connection instances 
        for trader in running_traders:
            if trader.robot_connection["robot"]["_id"] == ObjectId(id):                          
                # Remove the stopped trader from the list
                running_traders.remove(trader)

        #update the robot 
        db.robots.update_one(
            {
                '_id':ObjectId(id)
            },
            { 
                "$set":{'active':False}
            }
        ) 
        #Tell the client that bot stopped
        socket.emit('bot',{
            "action":'bot_started',
            "data":{'id':id}
        })       
    else:
        print("Not allowed")

@socket.on('signal')
def handle_signal(data):   
    for trader in running_traders:
        if 'price' in data and data['price']:                
            trader.pending_order(data)
        else:
            trader.trade(data['symbol'],data['action'],data['option'])

    if not len(running_traders):        
        db.robots.update_many({}, 
            {
                "$set": 
                { 
                    "active": False
                } 
            },
        )   
        socket.emit('no_bot_running',{}) 

@socket.on('delete_pending_order')
def handle_delete_pending_order(data):    
    for trader in running_traders:
        trader.delete_pending_order(ObjectId(data['id']))
    
def populate_connection(connection):
    connection['connector'] = db.users.find_one({'_id': connection['connector']}, {'_id': 1, 'firstName': 1, 'lastName': 1})
    connection['category'] = db.categories.find_one({'_id': connection['category']}, {'_id': 1, 'name': 1})
    connection['account'] = db.accounts.find_one({'_id': connection['account']}, {'_id': 1, 'account_name': 1, 'balance': 1, 'email':1, 'token':1, 'account_type':1})
    connection['robot'] = db.robots.find_one({'_id': connection['robot']}, {'_id': 1, 'name': 1, 'version': 1, 'symbols':1})
    
    return connection

if __name__=='__main__': 
   socket.run(app) 