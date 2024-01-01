import time, sys
from iqoptionapi.stable_api import IQ_Option
from database import db
from socket_manager import emit, send, socket
from bson import ObjectId
import bson.json_util as json_util
from decouple import config
import numpy
from datetime import datetime


class Trader:
    def __init__(self, email, password,risk_management, account_type="PRACTICE"):
        self.email = email
        self.password = password
        self.robot_connection_id = risk_management['robot_connection_id']
        self.daily_risk = risk_management['maximum_risk_']
        self.daily_target = risk_management['maximum_risk_target']
        self.risk_type = risk_management['risk_type']
        self.risk_percentage = risk_management['risk_percentage']
        self.stake_percentage = risk_management['stake_percentage']
        self.total_profit = 0
        self.curr_balance = 0
        self.stake = risk_management['stake']
        self.expiration = risk_management['expiration'] 
        self.robot_connection = risk_management['robot_connection']
        self.pending_orders = {}
        print("Email : ", email)        
        self.API = IQ_Option(self.email, self.password)
        self.API.connect()



        try:
            if not self.API.check_connect():
                if self.API.connect() == True:
                    print(f"IQOption API Version: {self.API.__version__} Connected Successfully")
                else:
                    print("Oops, connection failed. Use correct details or check internet connection")
            else:
                print("Already connected to IQOption API")
            
            if account_type:
                self.API.change_balance(account_type)
    
        except Exception as e:
            print(f"Error during initialization: {e}") 

        balance = self.API.get_balance()        
        self.notify_bot_started(balance)   


    def calculateStake(self):
        """Calculate amount size to use on each trade"""
        # flat #martingale #compound_all #compund_profit_only #balance_percentage
        account_balance = self.API.get_balance()
        if account_balance is None or account_balance < 1:
            sys.exit()

        # Check if account is not going to loss below target
        if self.risk_percentage != 0:
            self.curr_balance
            if account_balance > self.curr_balance:
                self.curr_balance = account_balance
                print(self.curr_balance)

            elif account_balance < self.curr_balance and account_balance <= (((100-self.risk_percentage)/100)*self.curr_balance):
                print(
                    f"We are now losing {self.risk_percentage}% below of the amount we made or invested")
                sys.exit()

        if account_balance >= self.daily_target:
            print("Target reached - ",self.email)
            db.connections.update_one(
                {
                    '_id':ObjectId(self.robot_connection_id)
                },
                { 
                    "$set":{'target_reached':True}
                }
            )
            socket.emit("bot",{
                "action":"target_reached",
                "data":json_util.dumps(self.robot_connection)
            })
            sys.exit()

        elif account_balance <= self.daily_risk:
            print("Loss reached")
            #TODO Socket
            sys.exit()

        if self.risk_type == 'FLAT':
            return self.stake

        elif self.risk_type == 'BALANCE PERCENTAGE':
            balance_percentage_amount = round(
                (self.stake_percentage / 100 * account_balance), 2)
            print(
                f"Balance Percentage Risk Type : {balance_percentage_amount}")
            if balance_percentage_amount > 20000:
                return 20000
            elif balance_percentage_amount < 1:
                return 1
            else:
                return balance_percentage_amount

        elif self.risk_type == 'COMPOUND ALL':
            all = round(account_balance, 2)
            print(f"All In Risk Type : {all}")
            return all
        
        elif self.risk_type == 'MARTINGALE':            
            return self.martingale()
    
    def openPositions(self):
        """Return number of open positions"""

        # binary = API.get_positions("turbo-option")[1]['total'] /# Not woriking
        digital = self.API.get_positions("digital-option")[1]['total']

        return digital

    def trade(self, symbol, action, option):
        """Execute Trade for digital""" 
        start_time = time.time()  # Execution starting time

        # Local Variables to use
        open_positions = self.openPositions()
        stake = self.calculateStake()

        # Check if there are running trades first
        if open_positions > 0:
            print("Trade failed because there is a running position.")

        elif open_positions == 0:
            # Entry Success notification
            def successEntryNotification(id, end_time):
                try:
                    #update database balance
                    
                    print(
                        f"ID: {id} Symbol: {symbol} - {action.title()} Order executed successfully")
                    print(
                        f"Execution Time : {round((end_time-start_time),3)} secs")
                    
                    self.notify_entry_open(id,symbol,action)
                except Exception as e:
                    print(f"Error in successEntryNotification: {e}")


            # Entry Fail notification
            def failedEntryNotification():
                print(
                    f"{symbol} Failed to execute maybe your balance low or asset is closed")
                balance = self.API.get_balance()
                print(f"Current Balance: {balance}")

                time.sleep(60*4)

            # DIGITAL TRADING
            if option == "digital":
                self.API.subscribe_strike_list(symbol,self.expiration)
                print({"symbol":symbol,"stake":stake, "action":action,"expiration":self.expiration })
                check, id = self.API.buy_digital_spot(
                    symbol, stake, action, self.expiration)  # Enter
                end_time = time.time()  # Execution finishing time

                if check == True:
                    successEntryNotification(id, end_time)
                    # Currently only for digital available
                    self.watchTrade(id, symbol, stake)
                else:
                    failedEntryNotification()

            # BINARY TRADING
            elif option == "binary":
                check, id = self.API.buy(stake, symbol, action, self.expiration)  # Enter
                end_time = time.time()  # Execution finishing time

                if check == True:
                    successEntryNotification(id, end_time)
                else:
                    failedEntryNotification()

    def martingale(self):
        try:
            # Get the robot_connection using robot_connection id (Replace this with your MongoDB query)
            robot_connection = db.connections.find_one({'_id':ObjectId(self.robot_connection_id)})

            if robot_connection is None:
                print("Robot connection not found.",self.robot_connection_id)
                return None

            total_last_stakes = 0
            new_stake = 0

            for i in range(1, robot_connection['current_level'] + 1):
                new_stake = (robot_connection['stake'] * i * robot_connection['payout'] + total_last_stakes) / robot_connection['payout']
                total_last_stakes += (robot_connection['stake'] * i * robot_connection['payout'] + total_last_stakes) / robot_connection['payout']

            # Round the stake based on the currency
            rounded_stake = new_stake if robot_connection['currency'] == "BTC" else round(new_stake, 2)
            return rounded_stake
        except Exception as e:
                    print(f"Error in martingale: {e}")
    
    def calculate_dynamic_stake(self, current_balance):
        try:       
            if self.robot_connection['current_level'] == 1:
                stake = 0
                if self.robot_connection['currency'] == "BTC":
                    stake = round(float(config('APP_MULTIPLIER')) * current_balance, 8)
                else:
                    stake = round(float(config('APP_MULTIPLIER')) * current_balance * 100) / 100
                
                #update the robot 
                db.connections.update_one(
                    {
                        '_id':ObjectId(self.robot_connection_id)
                    },
                    { 
                        "$set":{'stake':stake}
                    }
                )  
        except Exception as e:
                    print(f"Error in calculate_dynamic_stake: {e}")

    def watchTrade(self, id, symbol, stake):
        """"Monitoring Opened position"""
        previous_profit = 0
        while True:
            check, win = self.API.check_win_digital_v2(id)
            current_profit = self.API.get_digital_spot_profit_after_sale(id)
            if previous_profit != current_profit:
                socket.emit("bot",{
                    "action":"current_profit",
                    "data":{
                        "_id":self.robot_connection_id,
                        "current_profit":round(current_profit,2)
                    }
                })
                previous_profit = current_profit

            if check == True:
                break

        if win < 0:
            # Lose Notification
            total_profit = round((self.total_profit - stake), 2)
            win_result = f"\n{symbol} Won Profit is now $0 and loss -${stake}  => Total Profit = ${round(total_profit, 2)}"
            with open('trade_results.txt', 'a') as f:
                f.write(win_result)
            print(f"{symbol} Lost")
            self.notify_entry_close(0-stake)
        else:
            # Win Notification
            self.total_profit += round(win, 2)
            win_result = f"\n{symbol} Won Profit is now ${round(win,2)} and loss $0 => Total Profit = ${self.total_profit}"
            with open('trade_results.txt', 'a') as f:
                f.write(win_result)
            print(f"{symbol} Won")  
            self.notify_entry_close(round(win,2))    

        time.sleep(60*3)
    
    def notify_bot_started(self, balance):
        try:      
            if balance:  
                #Update stake if dynamic_stake is true
                is_dynamic_stake = self.robot_connection["dynamic_stake"]
                if is_dynamic_stake:
                    self.calculate_dynamic_stake(balance)
                #Update active symbols in robots collection
                symbols = self.API.get_all_open_time()     
                active_symbols = [{'name': symbol, 'active': values['open']} for symbol, values in symbols["digital"].items() if values['open']]  
            
                #update the robot 
                db.robots.update_one(
                    {
                        '_id':ObjectId(self.robot_connection['robot']['_id'])
                    },
                    { 
                        "$set":{'active':True, 'symbols':active_symbols}
                    }
                )

                db.accounts.update_one(
                    {
                        '_id':ObjectId(self.robot_connection['account']['_id'])
                    },
                    {
                        "$set":{
                            'balance':balance
                        }
                    }
                )

                #Tell the client that bot started
                socket.emit('bot',{
                    "action":'bot_started',
                    "data":json_util.dumps(self.robot_connection)
                })
        except Exception as e:
                    print(f"Error in notify_bot_started: {e}")
    
    def notify_entry_close(self, profit):
        #Update account in database
        try:
            current_balance = self.API.get_balance()
            robot_connection = db.connections.find_one({'_id':ObjectId(self.robot_connection_id)})
            level = robot_connection['current_level']

            current_level = level + 1 if profit <= 0 else 1

            db.accounts.update_one(
                {
                    '_id':ObjectId(self.robot_connection['account']['_id'])
                },
                {
                    "$set":{
                        'balance':current_balance
                    }
                }
            )

            db.connections.update_one(
                {
                    '_id':ObjectId(self.robot_connection_id)
                },
                { 
                    "$set":{'last_profit':profit, 'active_contract_id':0, 'entry':'', 'open_trade':False, 'current_level':current_level}
                }
            )

            socket.emit('bot', {
                "action": 'closed_trade',
                "data": {
                     '_id':self.robot_connection_id
                }
            })        
        except Exception as e:
                    print(f"Error in notify_entry_close: {e}")
    
    def notify_entry_open(self,id,symbol, action): 
        try:       
            current_balance = self.API.get_balance()         
            db.accounts.update_one(
                {
                    '_id':ObjectId(self.robot_connection['account']['_id'])
                },
                {
                    "$set":{
                        'balance':current_balance
                    }
                }
            )
            db.connections.update_one(
                {
                    '_id':ObjectId(self.robot_connection_id)
                },
                { 
                    "$set":{'active_contract_id':id, 'entry':f"{symbol}-{action.title()}", 'open_trade':True}
                }
            )
            socket.emit('bot', {
                "action": 'trade_success',
                "data": json_util.dumps(self.robot_connection) 
            })
        except Exception as e:
                    print(f"Error in notify_entry_open: {e}")
    
    def delete_pending_order(self, id):
        if id in self.pending_orders:
            self.pending_orders[id]['active'] = False
            db.pending_orders.update_one(
                {
                    '_id':ObjectId(id)
                },
                { 
                    "$set":{'active':False}
                }
            )
            socket.emit("pending_order_deleted",{})
        

    def getData(self,candles):
        """Get live open,close,high,low prices in array form"""

        data = {'open': numpy.array([]), 'high': numpy.array([]), 'low': numpy.array([]), 'close': numpy.array([]), 'volume': numpy.array([]) }
        for x in list(candles):
            data['open'] = numpy.append(data['open'], candles[x]['open'])
            data['high'] = numpy.append(data['open'], candles[x]['max'])
            data['low'] = numpy.append(data['open'], candles[x]['min'])
            data['close'] = numpy.append(data['open'], candles[x]['close'])
            data['volume'] = numpy.append(data['open'], candles[x]['volume'])
        return data
    
    def pending_order(self,data): 
        """"We send parameter and start to loop waiting for our pending orders positions to meet
        and then execue the trade then exit the loop. That's how we are setting the pending orders."""   
        timeframe = int(config("TIMEFRAME"))
        maxdict = 280

        #add_pending order to the database
        insert_data = {
             **data,
             'connection':ObjectId(self.robot_connection_id),
             'connector':ObjectId(self.robot_connection['connector']['_id']),
             'active':True,
             'createdAt': datetime.now()
        }       
        result = db.pending_orders.insert_one(insert_data) # add to database
        id = result.inserted_id
        self.pending_orders[id] = {'active': True} # add to global variable 

        self.API.start_candles_stream(data['symbol'],timeframe,maxdict)  
        candles = self.API.get_realtime_candles(data['symbol'], timeframe)
        prev_price = 0

        socket.emit('pending_order_success',{
            '_id':data['symbol']
        })

        while self.pending_orders[id]['active']:
            try:
                candle = self.getData(candles)
                        
            except KeyError:
                    pass
            else:      
                curr_price = candle["close"][-1]
                if prev_price != curr_price:
                    print(f"Current Price : {curr_price} => Pending Order : {data['price']} => Prev Price : {prev_price}")
        
                if curr_price != prev_price and prev_price != 0: # check if the price changed
                    if data['action'] == 'buy_stop' and prev_price != 0: #deal with pending buy stop
                        if prev_price <= data["price"] and curr_price >= data["price"]:
                            self.trade(data['symbol'], "call", data['option'])
                            break
                    
                    elif data['action'] == 'buy_limit' and prev_price != 0: #deal with pending buy limit
                        if prev_price >= data["price"] and curr_price <= data["price"]:
                            self.trade(data['symbol'], "call", data['option'])
                            break
                    
                    elif data['action'] == 'sell_stop' and prev_price != 0: #deal with pending sell stop
                        if prev_price >= data["price"] and curr_price <= data["price"]:
                            self.trade(data['symbol'], "put", data['option'])
                            break
                    
                    elif data['action'] == 'sell_limit' and prev_price != 0: #deal with pending sell limit
                        if prev_price <= data["price"] and curr_price >= data["price"]:
                            self.trade(data['symbol'], "put", data['option'])
                            break

            prev_price = curr_price 
    

    
        