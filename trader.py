import time, sys
from iqoptionapi.stable_api import IQ_Option
from database import db
from socket_manager import emit, send, socket
from bson import ObjectId
import bson.json_util as json_util

class Trader:
    def __init__(self, email, password,risk_management,api_instance, account_type="PRACTICE"):
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
        print("Email : ", email, "=> password: ", password)  
        self.API = api_instance    
        # self.API = IQ_Option(email, password)
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
        account_balance = self.API.get_balance()
        print("Balance : ", account_balance)   


    def calculateStake(self):
        """Calculate amount size to use on each trade"""
        # flat #martingale #compound_all #compund_profit_only #balance_percentage
        account_balance = self.API.get_balance()
        print("Balance : ", account_balance)
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
            print("Target reached")
            #TODO Socket
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
        print("Trade : ",symbol)
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
                socket.emit
                print(
                    f"ID: {id} Symbol: {symbol} - {action.title()} Order executed successfully")
                print(
                    f"Execution Time : {round((end_time-start_time),3)} secs")
                #Socket response here

            # Entry Fail notification
            def failedEntryNotification():
                print(
                    f"{symbol} Failed to execute maybe your balance low or asset is closed")
               
                time.sleep(60*4)

            # DIGITAL TRADING
            if option == "digital":
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

        print(f"Martingale Stake: {rounded_stake}")
        return rounded_stake
    

    def watchTrade(self, id, symbol, stake):
        """"Monitoring Opened position"""

        while True:
            check, win = self.API.check_win_digital_v2(id)
            if check == True:
                break

        if win < 0:
            # Lose Notification
            total_profit = round((self.total_profit - stake), 2)
            win_result = f"\n{symbol} Won Profit is now $0 and loss -${stake}  => Total Profit = ${round(total_profit, 2)}"
            with open('trade_results.txt', 'a') as f:
                f.write(win_result)
            print(f"{symbol} Lost")
         

        else:
            # Win Notification
            self.total_profit += round(win, 2)
            win_result = f"\n{symbol} Won Profit is now ${round(win,2)} and loss $0 => Total Profit = ${self.total_profit}"
            with open('trade_results.txt', 'a') as f:
                f.write(win_result)
            print(f"{symbol} Won")      

        time.sleep(60*3)
    
    def notify_bot_started(self, balance):      
        if balance:            
            #update the robot 
            db.robots.update_one(
                {
                    '_id':ObjectId(self.robot_connection['robot']['_id'])
                },
                { 
                    "$set":{'active':True}
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