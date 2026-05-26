import time
import json
from datetime import datetime

# Anti-pattern: Variável global mutável compartilhada
global_log = []

class u: # Code smell: Nome de classe ruim e fora do padrão CamelCase
    def __init__(self, n, a, i):
        self.name = n
        self.age = a
        self.id = i
        self.balance = 0.0
        self.status = "ACTIVE"
        self.history = []

class sistema: # Code smell: Nome em minúsculo
    def __init__(self):
        self.users = []
        self.system_status = 1
        self.admin_email = "admin@banco.com"

    def add_usr(self, u_obj):
        # Code smell: Aninhamento profundo (Arrow Anti-Pattern)
        if u_obj != None:
            if u_obj.age >= 18:
                if u_obj.id not in [x.id for x in self.users]:
                    self.users.append(u_obj)
                    global_log.append("User added: " + str(u_obj.id))
                    return True
                else:
                    print("error")
                    return False
            else:
                print("underage")
                return False
        return False

    def process_transaction(self, t_type, uid, amount, dest_id=None):
        # Code smell: Método gigante, alta complexidade ciclomática
        time.sleep(0.1) # Simulando latência
        if self.system_status == 1:
            if t_type == "DEP": # Code smell: Strings mágicas espalhadas
                for user in self.users:
                    if user.id == uid:
                        if user.status == "ACTIVE":
                            user.balance = user.balance + amount
                            user.history.append("DEP " + str(amount) + " " + str(time.time()))
                            global_log.append("dep success")
                            return 1
                        else:
                            return -1
            elif t_type == "WIT":
                for user in self.users:
                    if user.id == uid:
                        if user.status == "ACTIVE":
                            if user.balance >= amount:
                                if amount <= 5000: # Code smell: Número mágico escondido no código
                                    user.balance = user.balance - amount
                                    user.history.append("WIT " + str(amount) + " " + str(time.time()))
                                    return 1
                                else:
                                    return -2
                            else:
                                return -3
            elif t_type == "TRANS":
                # Code smell: Lógica duplicada e ineficiente para buscar usuários
                sender = None
                receiver = None
                for user in self.users:
                    if user.id == uid:
                        sender = user
                    if user.id == dest_id:
                        receiver = user
                if sender != None and receiver != None:
                    if sender.status == "ACTIVE" and receiver.status == "ACTIVE":
                        if sender.balance >= amount:
                            sender.balance -= amount
                            receiver.balance += amount
                            sender.history.append("TRANS OUT " + str(amount) + " to " + str(receiver.id))
                            receiver.history.append("TRANS IN " + str(amount) + " from " + str(sender.id))
                            return 1
        return 0

    def do_stuff_with_data(self, data):
        # Code smell: Método inútil, sem responsabilidade clara (God Object em formação)
        res = []
        for i in range(len(data)):
            if type(data[i]) == dict:
                if "val" in data[i]:
                    val = data[i]["val"]
                    if val > 100:
                        res.append(val * 0.9)
                    else:
                        res.append(val)
            elif type(data[i]) == int:
                res.append(data[i] * 1)
        
        try:
            # Code smell: Abrindo arquivo sem gerenciador de contexto (with)
            f = open("temp_data.txt", "w")
            f.write(str(res))
        except Exception as e:
            # Code smell: Engolindo exceções (Swallowing exceptions)
            pass 
        
        return res

    def generate_report(self):
        # Code smell: Concatenação de strings em loop (ineficiente em Python)
        out = "--- REPORT ---\n"
        total_money = 0
        for usr in self.users:
            out += "User: " + usr.name + " | Bal: " + str(usr.balance) + "\n"
            total_money += usr.balance
        
        out += "TOTAL IN BANK: " + str(total_money) + "\n"
        if total_money > 1000000:
            out += "WARNING: HIGH VOLUME\n"
        
        return out

def calc_loan(user_obj, amount, months):
    # Code smell: Função solta modificando o estado de um objeto, e variáveis não utilizadas
    x = 10 
    if user_obj.status == "ACTIVE":
        if user_obj.balance > amount * 0.2:
            rate = 0.05
            if months > 12:
                rate = 0.08
            if months > 24:
                rate = 0.12
            
            total = amount + (amount * rate)
            monthly = total / months
            user_obj.balance += amount
            user_obj.history.append("LOAN APPROVED " + str(amount))
            return monthly
    return 0

if __name__ == "__main__":
    # Script de teste rápido
    s = sistema()
    u1 = u("Joao", 25, 1)
    u2 = u("Maria", 17, 2) # Será rejeitada por ser menor de idade
    u3 = u("Pedro", 40, 3)

    s.add_usr(u1)
    s.add_usr(u2)
    s.add_usr(u3)

    s.process_transaction("DEP", 1, 1000)
    s.process_transaction("DEP", 3, 5000)
    s.process_transaction("WIT", 1, 200)
    s.process_transaction("TRANS", 3, 1000, 1)

    print(s.generate_report())
    print("Parcela do empréstimo:", calc_loan(u1, 5000, 24))