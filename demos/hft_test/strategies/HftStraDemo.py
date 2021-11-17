from wtpy import BaseHftStrategy
from wtpy import HftContext

from datetime import datetime

def makeTime(date:int, time:int, secs:int):
    '''
    将系统时间转成datetime\n
    @date   日期，格式如20200723\n
    @time   时间，精确到分，格式如0935\n
    @secs   秒数，精确到毫秒，格式如37500
    '''
    return datetime(year=int(date/10000), month=int(date%10000/100), day=date%100, 
        hour=int(time/100), minute=time%100, second=int(secs/1000), microsecond=secs%1000*1000)

class HftStraDemo(BaseHftStrategy):

    def __init__(self, name:str, code:str, expsecs:int, offset:int, freq:int=30):
        BaseHftStrategy.__init__(self, name)

        '''交易参数'''
        self.__code__ = code            #交易合约
        self.__expsecs__ = expsecs      #订单超时秒数
        self.__offset__ = offset        #指令价格偏移
        self.__freq__ = freq            #交易频率控制，指定时间内限制信号数，单位秒

        '''内部数据'''
        self.__last_tick__ = None       #上一笔行情
        self.__orders__ = dict()        #策略相关的订单
        self.__last_entry_time__ = None #上次入场时间
        self.__cancel_cnt__ = 0         #正在撤销的订单数
        self.__channel_ready__ = False  #通道是否就绪
        

    def on_init(self, context:HftContext):
        '''
        策略初始化，启动的时候调用\n
        用于加载自定义数据\n
        @context    策略运行上下文
        '''

        #先订阅实时数据
        context.stra_sub_ticks(self.__code__)

        self.__ctx__ = context

    def check_orders(self):
        #如果未完成订单不为空
        if len(self.__orders__.keys()) > 0 and self.__last_entry_time__ is not None:
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
            span = now - self.__last_entry_time__
            if span.total_seconds() > self.__expsecs__: #如果订单超时，则需要撤单
                for localid in self.__orders__:
                    self.__ctx__.stra_cancel(localid)
                    self.__cancel_cnt__ += 1
                    self.__ctx__.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))

    def on_tick(self, context:HftContext, stdCode:str, newTick:dict):
        if self.__code__ != stdCode:
            return

        #如果有未完成订单，则进入订单管理逻辑
        if len(self.__orders__.keys()) != 0:
            self.check_orders()
            return

        if not self.__channel_ready__:
            return

        self.__last_tick__ = newTick

        #如果已经入场，则做频率检查
        if self.__last_entry_time__ is not None:
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
            span = now - self.__last_entry_time__
            if span.total_seconds() <= 30:
                return

        #信号标志
        signal = 0
        #最新价作为基准价格
        price = newTick["price"]
        #计算理论价格
        pxInThry = (newTick["bidprice"][0]*newTick["askqty"][0] + newTick["askprice"][0]*newTick["bidqty"][0]) / (newTick["askqty"][0] + newTick["bidqty"][0])

        context.stra_log_text("理论价格%f，最新价：%f" % (pxInThry, price))

        if pxInThry > price:    #理论价格大于最新价，正向信号
            signal = 1
            context.stra_log_text("出现正向信号")
        elif pxInThry < price:  #理论价格小于最新价，反向信号
            signal = -1
            context.stra_log_text("出现反向信号")

        if signal != 0:
            #读取当前持仓
            curPos = context.stra_get_position(self.__code__)
            #读取品种属性，主要用于价格修正
            commInfo = context.stra_get_comminfo(self.__code__)
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())

            #如果出现正向信号且当前仓位小于等于0，则买入
            if signal > 0 and curPos <= 0:
                #买入目标价格=基准价格+偏移跳数*报价单位
                targetPx = price + commInfo.pricetick * self.__offset__

                #执行买入指令，返回所有订单的本地单号
                ids = context.stra_buy(self.__code__, targetPx, 1, "buy")

                #将订单号加入到管理中
                for localid in ids:
                    self.__orders__[localid] = localid
                
                #更新入场时间
                self.__last_entry_time__ = now

            #如果出现反向信号且当前持仓大于等于0，则卖出
            elif signal < 0 and curPos >= 0:
                #买入目标价格=基准价格-偏移跳数*报价单位
                targetPx = price - commInfo.pricetick * self.__offset__

                #执行卖出指令，返回所有订单的本地单号
                ids = context.stra_sell(self.__code__, targetPx, 1, "sell")

                #将订单号加入到管理中
                for localid in ids:
                    self.__orders__[localid] = localid
                
                #更新入场时间
                self.__last_entry_time__ = now


    def on_bar(self, context:HftContext, stdCode:str, period:str, newBar:dict):
        return

    def on_channel_ready(self, context:HftContext):
        undone = context.stra_get_undone(self.__code__)
        if undone != 0 and len(self.__orders__.keys()) == 0:
            context.stra_log_text("%s存在不在管理中的未完成单%f手，全部撤销" % (self.__code__, undone))
            isBuy = (undone > 0)
            ids = context.stra_cancel_all(self.__code__, isBuy)
            for localid in ids:
                self.__orders__[localid] = localid
            self.__cancel_cnt__ += len(ids)
            context.stra_log_text("cancelcnt -> %d" % (self.__cancel_cnt__))
        self.__channel_ready__ = True

    def on_channel_lost(self, context:HftContext):
        context.stra_log_text("交易通道连接丢失")
        self.__channel_ready__ = False

    def on_entrust(self, context:HftContext, localid:int, stdCode:str, bSucc:bool, msg:str, userTag:str):
        if bSucc:
            context.stra_log_text("%s下单成功，本地单号：%d" % (stdCode, localid))
        else:
            context.stra_log_text("%s下单失败，本地单号：%d，错误信息：%s" % (stdCode, localid, msg))

    def on_order(self, context:HftContext, localid:int, stdCode:str, isBuy:bool, totalQty:float, leftQty:float, price:float, isCanceled:bool, userTag:str):
        if localid not in self.__orders__:
            return

        if isCanceled or leftQty == 0:
            self.__orders__.pop(localid)
            if self.__cancel_cnt__ > 0:
                self.__cancel_cnt__ -= 1
                self.__ctx__.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))
        return

    def on_trade(self, context:HftContext, localid:int, stdCode:str, isBuy:bool, qty:float, price:float, userTag:str):
        return


class myTestHftStrat(BaseHftStrategy):
    
    def __init__(self, name:str, code:str, expsecs:int, offset:int, freq:int=30):
        BaseHftStrategy.__init__(self, name)

        '''交易参数'''
        self.__code__ = code            #交易合约
        self.__expsecs__ = expsecs      #订单超时秒数
        self.__offset__ = offset        #指令价格偏移
        self.__freq__ = freq            #交易频率控制，指定时间内限制信号数，单位秒

        '''内部数据'''
        self.__last_tick__ = None       #上一笔行情
        self.__orders__ = dict()        #策略相关的订单
        self.__last_entry_time__ = None #上次入场时间
        self.__cancel_cnt__ = 0         #正在撤销的订单数
        self.__channel_ready__ = False  #通道是否就绪
        

    def on_init(self, context:HftContext):
        '''
        策略初始化，启动的时候调用\n
        用于加载自定义数据\n
        @context    策略运行上下文
        '''

        #先订阅实时数据
        #context.stra_get_ticks(self.__code__, count= 10000)
        context.stra_sub_ticks(self.__code__)
        commInfo = context.stra_get_comminfo(self.__code__)
        self.__ctx__ = context

    def check_orders(self):
        #如果未完成订单不为空
        if len(self.__orders__.keys()) > 0 and self.__last_entry_time__ is not None:
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
            span = now - self.__last_entry_time__
            if span.total_seconds() > self.__expsecs__: #如果订单超时，则需要撤单
                for localid in self.__orders__:
                    self.__ctx__.stra_cancel(localid)
                    self.__cancel_cnt__ += 1
                    self.__ctx__.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))

    def on_tick(self, context:HftContext, stdCode:str, newTick:dict):
        if self.__code__ != stdCode:
            return

        #如果有未完成订单，则进入订单管理逻辑
        if len(self.__orders__.keys()) != 0:
            self.check_orders()
            return

        if not self.__channel_ready__:
            return

        self.__last_tick__ = newTick

        #如果已经入场，则做频率检查
        if self.__last_entry_time__ is not None:
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
            span = now - self.__last_entry_time__
            if span.total_seconds() <= 30:
                return

        #信号标志
        signal = 0
        #最新价作为基准价格
        price = newTick["price"]
        
        #当前时间，一定要从api获取，不然回测会有问题
        now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
        #读取当前持仓
        curPos = context.stra_get_position(self.__code__)
        
        if now.minute == 12 and curPos <= 0:
            #读取品种属性，主要用于价格修正
            commInfo = context.stra_get_comminfo(self.__code__)
            context.stra_log_text("买入")
            #买入目标价格=基准价格+偏移跳数*报价单位
            targetPx = price + commInfo.pricetick * self.__offset__

            #执行买入指令，返回所有订单的本地单号
            ids = context.stra_buy(self.__code__, targetPx, 10, "buy")

            #将订单号加入到管理中
            for localid in ids:
                self.__orders__[localid] = localid
            
            #更新入场时间
            self.__last_entry_time__ = now
            
        if now.minute == 48 and curPos >= 0:
            #读取品种属性，主要用于价格修正
            commInfo = context.stra_get_comminfo(self.__code__)
            context.stra_log_text("卖出")
            #买入目标价格=基准价格+偏移跳数*报价单位
            targetPx = price - commInfo.pricetick * self.__offset__

            #执行卖出指令，返回所有订单的本地单号
            ids = context.stra_sell(self.__code__, targetPx, 10, "sell")

            #将订单号加入到管理中
            for localid in ids:
                self.__orders__[localid] = localid
            
            #更新入场时间
            self.__last_entry_time__ = now

    def on_bar(self, context:HftContext, stdCode:str, period:str, newBar:dict):
        return

    def on_channel_ready(self, context:HftContext):
        undone = context.stra_get_undone(self.__code__)
        if undone != 0 and len(self.__orders__.keys()) == 0:
            context.stra_log_text("%s存在不在管理中的未完成单%f手，全部撤销" % (self.__code__, undone))
            isBuy = (undone > 0)
            ids = context.stra_cancel_all(self.__code__, isBuy)
            for localid in ids:
                self.__orders__[localid] = localid
            self.__cancel_cnt__ += len(ids)
            context.stra_log_text("cancelcnt -> %d" % (self.__cancel_cnt__))
        self.__channel_ready__ = True

    def on_channel_lost(self, context:HftContext):
        context.stra_log_text("交易通道连接丢失")
        self.__channel_ready__ = False

    def on_entrust(self, context:HftContext, localid:int, stdCode:str, bSucc:bool, msg:str, userTag:str):
        if bSucc:
            context.stra_log_text("%s下单成功，本地单号：%d" % (stdCode, localid))
        else:
            context.stra_log_text("%s下单失败，本地单号：%d，错误信息：%s" % (stdCode, localid, msg))

    def on_order(self, context:HftContext, localid:int, stdCode:str, isBuy:bool, totalQty:float, leftQty:float, price:float, isCanceled:bool, userTag:str):
        if localid not in self.__orders__:
            return

        if isCanceled or leftQty == 0:
            self.__orders__.pop(localid)
            if self.__cancel_cnt__ > 0:
                self.__cancel_cnt__ -= 1
                self.__ctx__.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))
        return

    def on_trade(self, context:HftContext, localid:int, stdCode:str, isBuy:bool, qty:float, price:float, userTag:str):
        return


class myTestHftArbitrageStrat(BaseHftStrategy):
    
    def __init__(self, name:str, code1:str, code2:str, expsecs:int, offset:int, freq:int=30, sizeofbet:int=1):
        BaseHftStrategy.__init__(self, name)
        print("__init__")
        '''交易参数'''
        self.__code_1__ = code1            #交易合约1
        self.__code_2__ = code2            #交易合约2
        self.__expsecs__ = expsecs      #订单超时秒数
        self.__offset__ = offset        #指令价格偏移
        self.__freq__ = freq            #交易频率控制，指定时间内限制信号数，单位秒

        '''内部数据'''
        self.__last_tick__ = None       #上一笔行情
        self.__orders__ = dict()        #策略相关的订单
        self.__last_entry_time__ = None #上次入场时间
        self.__cancel_cnt__ = 0         #正在撤销的订单数
        self.__channel_ready__ = False  #通道是否就绪
        self.newBars = 0
        self.sizeofbet = sizeofbet
        

    def on_init(self, context:HftContext):
        '''
        策略初始化，启动的时候调用\n
        用于加载自定义数据\n
        @context    策略运行上下文
        '''

        #先订阅实时数据
        #context.stra_get_ticks(self.__code__, count= 10000)
        context.stra_sub_ticks(self.__code_1__)
        context.stra_sub_ticks(self.__code_2__)
        context.stra_log_text("in on_init")
        print("on_init in print")
        self.__ctx__ = context

    def check_orders(self):
        #如果未完成订单不为空
        if len(self.__orders__.keys()) > 0 and self.__last_entry_time__ is not None:
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
            span = now - self.__last_entry_time__
            if span.total_seconds() > self.__expsecs__: #如果订单超时，则需要撤单
                for localid in self.__orders__:
                    self.__ctx__.stra_cancel(localid)
                    self.__cancel_cnt__ += 1
                    self.__ctx__.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))

    def on_tick(self, context:HftContext, stdCode:str, newTick:dict):
        
        context.stra_log_text("in on_tick" + " " + stdCode)
        
        if self.__code_1__ != stdCode and self.__code_2__ != stdCode:
            return

        #如果有未完成订单，则进入订单管理逻辑
        if len(self.__orders__.keys()) != 0:
            self.check_orders()
            return

        if not self.__channel_ready__:
            return

        self.__last_tick__ = newTick

        #如果已经入场，则做频率检查
        if self.__last_entry_time__ is not None:
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
            span = now - self.__last_entry_time__
            
        if self.newBars <= 1:
            print("on_tick in print" + stdCode)
            self.newBars += 1
        
        price = newTick['price']
        #print(newTick['askprice'])
        # 做多
        if self.__code_1__ == stdCode and (context.stra_get_position(self.__code_2__) + context.stra_get_position(self.__code_1__))!=0: # 只有远月合约有持仓了，再会去交易近月合约
            #读取品种属性，主要用于价格修正
            commInfo = context.stra_get_comminfo(stdCode)
            targetposition = -context.stra_get_position(self.__code_2__) - context.stra_get_position(self.__code_1__)
            iftrade = False
            if targetposition >0:
                context.stra_log_text("买入" + stdCode)
                print("买入" + stdCode +" at:"+str(now.hour)+":"+str(now.minute)+":"+str(now.second))
                targetPx = price + commInfo.pricetick * 20
                ids = context.stra_buy(stdCode, targetPx, targetposition, "buy_front")
                iftrade = True
            else:
                context.stra_log_text("卖出" + stdCode)
                print("卖出" + stdCode +" at:"+str(now.hour)+":"+str(now.minute)+":"+str(now.second))
                targetPx = price - commInfo.pricetick * 20
                ids = context.stra_sell(stdCode, targetPx, -targetposition, "sell_front")
                iftrade = True

            #将订单号加入到管理中
            if iftrade:
                for localid in ids:
                    self.__orders__[localid] = localid
            
        elif self.__code_2__ == stdCode and context.stra_get_position(self.__code_2__) >=0:
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
            #读取当前持仓
            curPos = context.stra_get_position(stdCode)
            iftrade = False
            
            if now.minute >=1 and now.minute <= 10 and curPos != -self.sizeofbet : # 在这个区间还没有做空一手
                #读取品种属性，主要用于价格修正
                commInfo = context.stra_get_comminfo(stdCode)
                # 如果有未完成订单，则走不到这里，所以我就在这里做空一手    
                context.stra_log_text("卖出" + stdCode)
                print("卖出" + stdCode +" at:"+str(now.hour)+":"+str(now.minute)+":"+str(now.second))
                targetPx = newTick['askprice'][0] - commInfo.pricetick
                ids = context.stra_sell(stdCode, targetPx, self.sizeofbet, "sell_far")
                iftrade = True
            elif now.minute > 10 and now.minute < 13 and curPos != -self.sizeofbet: # 出了这个区间还没有做空成功
                #读取品种属性，主要用于价格修正
                commInfo = context.stra_get_comminfo(stdCode)
                # 如果有未完成订单，则走不到这里，所以我就在这里做空一手
                context.stra_log_text("激烈卖出" + stdCode)
                print("激烈卖出" + stdCode +" at:"+str(now.hour)+":"+str(now.minute)+":"+str(now.second))
                targetPx = newTick['bidprice'][0] - commInfo.pricetick * 10
                ids = context.stra_sell(stdCode, targetPx, curPos + self.sizeofbet, "sell_far_2")
                iftrade = True
            if iftrade:
                #更新入场时间
                self.__last_entry_time__ = now
                #将订单号加入到管理中
                for localid in ids:
                    self.__orders__[localid] = localid
        elif self.__code_2__ == stdCode and context.stra_get_position(self.__code_2__) <0:# 已经做空了，那么就需要平仓
            #当前时间，一定要从api获取，不然回测会有问题
            now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
            #读取当前持仓
            curPos = context.stra_get_position(stdCode)
            iftrade = False
            if now.minute >=48 and now.minute <= 55 and curPos != 0: # 在这个区间还没有平仓
                # 如果有未完成订单，则走不到这里，所以我就在这里做空一手
                #读取品种属性，主要用于价格修正
                commInfo = context.stra_get_comminfo(stdCode)
                context.stra_log_text("买平" + stdCode)
                print("买平" + stdCode +" at:"+str(now.hour)+":"+str(now.minute)+":"+str(now.second))
                targetPx = newTick['bidprice'][0] + commInfo.pricetick
                ids = context.stra_buy(stdCode, targetPx, -curPos, "buyclose_far")
                iftrade = True
                
            elif now.minute > 55 and curPos != 0: # 出了这个区间 还没有平仓
                # 如果有未完成订单，则走不到这里，所以在这里更加激进的平仓
                #读取品种属性，主要用于价格修正
                commInfo = context.stra_get_comminfo(stdCode)
                context.stra_log_text("激烈买平" + stdCode)
                print("激烈买平" + stdCode +" at:"+str(now.hour)+":"+str(now.minute)+":"+str(now.second))
                targetPx = newTick['askprice'][0] + commInfo.pricetick * 10
                ids = context.stra_buy(stdCode, targetPx, -curPos, "buyclose_far_2")
                iftrade = True
            if iftrade:
                #将订单号加入到管理中
                for localid in ids:
                    self.__orders__[localid] = localid
                
                #更新入场时间
                self.__last_entry_time__ = now

        
    def on_tick_code_1(self, context:HftContext, stdCode:str, newTick:dict):
        #当前时间，一定要从api获取，不然回测会有问题
        now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
        #读取当前持仓
        curPos = context.stra_get_position(stdCode)
        
        price = newTick['price']
        if now.minute == 12 and curPos <= 0:
            #读取品种属性，主要用于价格修正
            commInfo = context.stra_get_comminfo(stdCode)
            context.stra_log_text("买入" + stdCode)
            print("买入" + stdCode)
            #买入目标价格=基准价格+偏移跳数*报价单位
            targetPx = price + commInfo.pricetick * self.__offset__

            #执行买入指令，返回所有订单的本地单号
            ids = context.stra_buy(stdCode, targetPx, 5, "buy")

            #将订单号加入到管理中
            for localid in ids:
                self.__orders__[localid] = localid
            
            #更新入场时间
            self.__last_entry_time__ = now
            
        if now.minute == 48 and curPos >= 0:
            #读取品种属性，主要用于价格修正
            commInfo = context.stra_get_comminfo(stdCode)
            context.stra_log_text("卖出" + stdCode)
            print("卖出" + stdCode)
            #买入目标价格=基准价格+偏移跳数*报价单位
            targetPx = price - commInfo.pricetick * self.__offset__

            #执行卖出指令，返回所有订单的本地单号
            ids = context.stra_sell(stdCode, targetPx, 5, "sell")

            #将订单号加入到管理中
            for localid in ids:
                self.__orders__[localid] = localid
            
            #更新入场时间
            self.__last_entry_time__ = now
    
    def on_tick_code_2(self, context:HftContext, stdCode:str, newTick:dict):
        #当前时间，一定要从api获取，不然回测会有问题
        now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
        #读取当前持仓
        curPos = context.stra_get_position(stdCode)
        
        price = newTick['price']
        if now.minute == 12 and curPos <= 0:
            #读取品种属性，主要用于价格修正
            commInfo = context.stra_get_comminfo(stdCode)
            context.stra_log_text("卖出" + stdCode)
            print("卖出" + stdCode)
            #买入目标价格=基准价格+偏移跳数*报价单位
            targetPx = price - commInfo.pricetick * self.__offset__

            #执行买入指令，返回所有订单的本地单号
            ids = context.stra_sell(stdCode, targetPx, 5, "sell")

            #将订单号加入到管理中
            for localid in ids:
                self.__orders__[localid] = localid
            
            #更新入场时间
            self.__last_entry_time__ = now
            
        if now.minute == 48 and curPos >= 0:
            #读取品种属性，主要用于价格修正
            commInfo = context.stra_get_comminfo(stdCode)
            context.stra_log_text("买入" + stdCode)
            print("买入" + stdCode)
            #买入目标价格=基准价格+偏移跳数*报价单位
            targetPx = price + commInfo.pricetick * self.__offset__

            #执行卖出指令，返回所有订单的本地单号
            ids = context.stra_buy(stdCode, targetPx, 5, "buy")

            #将订单号加入到管理中
            for localid in ids:
                self.__orders__[localid] = localid
            
            #更新入场时间
            self.__last_entry_time__ = now

    def on_bar(self, context:HftContext, stdCode:str, period:str, newBar:dict):
        return

    def on_channel_ready(self, context:HftContext):
        undone = context.stra_get_undone(self.__code_1__)
        if undone != 0 and len(self.__orders__.keys()) == 0:
            context.stra_log_text("%s存在不在管理中的未完成单%f手，全部撤销" % (self.__code_1__, undone))
            isBuy = (undone > 0)
            ids = context.stra_cancel_all(self.__code_1__, isBuy)
            for localid in ids:
                self.__orders__[localid] = localid
            self.__cancel_cnt__ += len(ids)
            context.stra_log_text("cancelcnt -> %d" % (self.__cancel_cnt__))
        self.__channel_ready__ = True

    def on_channel_lost(self, context:HftContext):
        context.stra_log_text("交易通道连接丢失")
        self.__channel_ready__ = False

    def on_entrust(self, context:HftContext, localid:int, stdCode:str, bSucc:bool, msg:str, userTag:str):
        if bSucc:
            context.stra_log_text("%s下单成功，本地单号：%d" % (stdCode, localid))
        else:
            context.stra_log_text("%s下单失败，本地单号：%d，错误信息：%s" % (stdCode, localid, msg))

    def on_order(self, context:HftContext, localid:int, stdCode:str, isBuy:bool, totalQty:float, leftQty:float, price:float, isCanceled:bool, userTag:str):
        if localid not in self.__orders__:
            return

        if isCanceled or leftQty == 0:
            self.__orders__.pop(localid)
            if self.__cancel_cnt__ > 0:
                self.__cancel_cnt__ -= 1
                self.__ctx__.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))
        return

    def on_trade(self, context:HftContext, localid:int, stdCode:str, isBuy:bool, qty:float, price:float, userTag:str):
        #当前时间，一定要从api获取，不然回测会有问题
        now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
        print("成交" + stdCode +" "+ str(qty)+" at:"+str(now.hour)+":"+str(now.minute)+":"+str(now.second))
        return
    
    def on_session_end(self, context:HftContext, curTDate:int):
        print("session ends")
        self.newBars = 0
        '''
        交易日结束事件

        @curTDate   交易日，格式为20210220
        '''
        return

class mySimpleArbitrageStrategy(BaseHftStrategy):
    
    def __init__(self, name:str, code1:str, code2:str, expsecs:int, offset:int, freq:int=30, sizeofbet:int=1):
        BaseHftStrategy.__init__(self, name)
        print("__init__")
        '''交易参数'''
        self.__code_1__ = code1            #交易合约1
        self.__code_2__ = code2            #交易合约2
        self.__expsecs__ = expsecs      #订单超时秒数
        self.__offset__ = offset        #指令价格偏移
        self.__freq__ = freq            #交易频率控制，指定时间内限制信号数，单位秒

        '''内部数据'''
        self.__last_tick__ = None       #上一笔行情
        self.__orders_1__ = dict()        #策略相关的订单
        self.__orders_2__ = dict()        #策略相关的订单
        self.__last_entry_time__ = None #上次入场时间
        self.__cancel_cnt__ = 0         #正在撤销的订单数
        self.__channel_ready__ = False  #通道是否就绪
        self.newBars = 0
        self.sizeofbet = sizeofbet
        self.algo = None
        

    def on_init(self, context:HftContext):
        '''
        策略初始化，启动的时候调用\n
        用于加载自定义数据\n
        @context    策略运行上下文
        '''

        #先订阅实时数据
        #context.stra_get_ticks(self.__code__, count= 10000)
        context.stra_sub_ticks(self.__code_1__)
        context.stra_sub_ticks(self.__code_2__)
        context.stra_log_text("in on_init")
        print("on_init in print")
        self.__ctx__ = context

    
    def on_tick(self, context:HftContext, stdCode:str, newTick:dict):
        context.stra_log_text("in on_tick" + " " + stdCode)
        if self.newBars <= 1:
            print("on_tick in print" + stdCode)
            self.newBars += 1
            
        if self.__code_1__ != stdCode and self.__code_2__ != stdCode:
            return

        if not self.__channel_ready__:
            return

        #当前时间，一定要从api获取，不然回测会有问题
        now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
        
        if stdCode == self.__code_1__:
            self.on_tick_code_1(context, stdCode, newTick, now)
            return
        
        #如果有未完成订单，则进入订单管理逻辑
        if len(self.__orders_2__.keys()) != 0 and self.algo is not None:
            for localid in self.__orders_2__:
                context.stra_cancel(localid)
                self.__cancel_cnt__ += 1
                #context.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))
                print("cancelcount -> %d" % (self.__cancel_cnt__))
            return
        
        
        if now.hour == 11 and now.minute == 1 and self.algo is None:
            # 启动策略
            print("on_tick initiated algo" +" at:"+now.__str__())
            self.algo = simpleOrderAlgo(initiatedTime=now, tradingHorizonMin=10,
                                            slotsTotal=10, slotsEachTime=2, code = self.__code_2__,
                                            codetradeDirection=-1, addtick = 100, coldSeconds = 20)
        
        if self.algo is not None:
            # 一个是算法要求，一个是风控要求
            if self.algo.isInTradingHorizon(now) and (context.stra_get_position(self.__code_2__) + context.stra_get_position(self.__code_1__))==0:
                # 返回order
                ids = self.algo.run_on_ticks(context=context, stdCode=stdCode,newTick=newTick,now=now,orders=self.__orders_2__)
                if ids is not None:
                    for localid in ids:
                        self.__orders_2__[localid] = localid        
            elif self.algo.isInTradingHorizon(now):
                print("on_tick algo ends" +" at:"+now.__str__())
                self.algo = None # 下马策略
         
        return
    
    def on_tick_code_1(self, context:HftContext, stdCode:str, newTick:dict, now:datetime):
        # 做多
        if (context.stra_get_position(self.__code_2__) + context.stra_get_position(self.__code_1__))!=0: # 只有远月合约有持仓了，再会去交易近月合约
            #读取品种属性，主要用于价格修正
            for key, item in self.__orders_1__.items():
                print("in on_tick_code_1 iterate dict")    
                print(key, item)
            if len(self.__orders_1__.keys()):
                # 还有订单没有完成
                return
            commInfo = context.stra_get_comminfo(stdCode)
            targetposition = -context.stra_get_position(self.__code_2__) - context.stra_get_position(self.__code_1__)
            iftrade = False
            if targetposition >0:
                context.stra_log_text("买入" + stdCode)
                targetPx = newTick['price'] + commInfo.pricetick * 20
                print("买入" + stdCode +" at " + str(commInfo.pricetick * 20) +" , "+now.__str__())
                
                ids = context.stra_buy(stdCode, targetPx, targetposition, "buy_front")
                iftrade = True
            else:
                context.stra_log_text("卖出" + stdCode)
                targetPx = newTick['price'] - commInfo.pricetick * 20
                print("卖出" + stdCode +" at " + str(- commInfo.pricetick * 20) +" , "+now.__str__())
                ids = context.stra_sell(stdCode, targetPx, -targetposition, "sell_front")
                iftrade = True

            #将订单号加入到管理中
            if iftrade:
                for localid in ids:
                    self.__orders_1__[localid] = localid
    
    def on_bar(self, context:HftContext, stdCode:str, period:str, newBar:dict):
        return

    def on_channel_ready(self, context:HftContext):
        undone = context.stra_get_undone(self.__code_1__)
        if undone != 0 and len(self.__orders_1__.keys()) == 0:
            context.stra_log_text("%s存在不在管理中的未完成单%f手，全部撤销" % (self.__code_1__, undone))
            isBuy = (undone > 0)
            ids = context.stra_cancel_all(self.__code_1__, isBuy)
            for localid in ids:
                self.__orders_1__[localid] = localid
            self.__cancel_cnt__ += len(ids)
            context.stra_log_text("cancelcnt -> %d" % (self.__cancel_cnt__))
            
        undone = context.stra_get_undone(self.__code_2__)
        if undone != 0 and len(self.__orders_2__.keys()) == 0:
            context.stra_log_text("%s存在不在管理中的未完成单%f手，全部撤销" % (self.__code_2__, undone))
            isBuy = (undone > 0)
            ids = context.stra_cancel_all(self.__code_2__, isBuy)
            for localid in ids:
                self.__orders_2__[localid] = localid
            self.__cancel_cnt__ += len(ids)
            context.stra_log_text("cancelcnt -> %d" % (self.__cancel_cnt__))
        self.__channel_ready__ = True

    def on_channel_lost(self, context:HftContext):
        context.stra_log_text("交易通道连接丢失")
        self.__channel_ready__ = False

    def on_entrust(self, context:HftContext, localid:int, stdCode:str, bSucc:bool, msg:str, userTag:str):
        if bSucc:
            context.stra_log_text("%s下单成功，本地单号：%d" % (stdCode, localid))
        else:
            context.stra_log_text("%s下单失败，本地单号：%d，错误信息：%s" % (stdCode, localid, msg))

    def on_order(self, context:HftContext, localid:int, stdCode:str, isBuy:bool, totalQty:float, leftQty:float, price:float, isCanceled:bool, userTag:str):
        if localid not in self.__orders_1__ and localid not in self.__orders_2__:
            return

        if localid in self.__orders_1__:
            if isCanceled or leftQty == 0:
                self.__orders_1__.pop(localid)
                if self.__cancel_cnt__ > 0:
                    self.__cancel_cnt__ -= 1
                    self.__ctx__.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))
        else:
            if isCanceled or leftQty == 0:
                self.__orders_2__.pop(localid)
                if self.__cancel_cnt__ > 0:
                    self.__cancel_cnt__ -= 1
                    self.__ctx__.stra_log_text("cancelcount -> %d" % (self.__cancel_cnt__))
        return

    def on_trade(self, context:HftContext, localid:int, stdCode:str, isBuy:bool, qty:float, price:float, userTag:str):
        #当前时间，一定要从api获取，不然回测会有问题
        now = makeTime(self.__ctx__.stra_get_date(), self.__ctx__.stra_get_time(), self.__ctx__.stra_get_secs())
        print("成交" + stdCode +" "+ str(qty)+" at:"+now.__str__())
        return
    
    def on_session_end(self, context:HftContext, curTDate:int):
        print("session ends")
        self.newBars = 0
        '''
        交易日结束事件

        @curTDate   交易日，格式为20210220
        '''
        return

class simpleOrderAlgo:
    '''
    最简单的一个挂单执行策略：
    initiatedTime: 策略的开始执行时间
    tradingHorizonMin: 从策略开始执行，过多久分钟结束
    slotsTotal: 最多执行多少手
    slotsEachTime: 单次挂多少手
    code: 标的
    codetradeDirection:交易方向
    addtick: 挂单价相对于买一和卖一让多少个tick
    coldSeconds: 两次挂单之间间隔的时间
    '''
    def __init__(self, initiatedTime:datetime,tradingHorizonMin:int, slotsTotal:int, slotsEachTime:int, code:str,codetradeDirection:int,addtick:int,coldSeconds:int):
        self.__initiatedTime__ = initiatedTime
        self.__tradingHorizonMin__ = tradingHorizonMin
        self.__slotsTotal__ = slotsTotal
        self.__slotsEachTime__ = slotsEachTime
        self.__code__ = code # 近月合约
        self.__codetradeDirection__ =  codetradeDirection # code的买卖方向，1表示买，-1表示卖
        self.__addtick__ = addtick # 激进程度
        self.count = 0
        self.__lastOrderTime__ = None
        self.__coldSeconds__ = coldSeconds
    
    def run_on_ticks(self, context:HftContext, stdCode:str, newTick:dict, now:datetime, orders:dict()):
        # 按照每个tick来触发
        ids = None
        if len(orders.keys()) == 0: # 没有待处理的订单了
            if self.count < self.__slotsTotal__ and not self.isInColdTime(now):
                # 先交易code_2
                commInfo = context.stra_get_comminfo(self.__code__)
                ids = None
                self.count += self.__slotsEachTime__
                self.__lastOrderTime__ = now
                if self.__codetradeDirection__ >0:
                    print("buy code, at " + now.__str__())
                    targetPx = newTick['bidprice'][0] + commInfo.pricetick * self.__addtick__
                    ids = context.stra_buy(self.__code__, targetPx, self.__slotsEachTime__, "buy_far")
                elif self.__codetradeDirection__ <0:
                    print("sell code, at " + now.__str__())
                    targetPx = newTick['askprice'][0] - commInfo.pricetick * self.__addtick__
                    ids = context.stra_sell(self.__code__, targetPx, self.__slotsEachTime__, "sell_far")
        return ids
            
    
    def isInTradingHorizon(self, now: datetime):
        diffMins = (now - self.__initiatedTime__).seconds/60.0 + (now - self.__initiatedTime__).microseconds/1000000.0/60.0
        return diffMins < self.__tradingHorizonMin__ and diffMins >= 0
    
    def isInColdTime(self, now: datetime):
        if self.__lastOrderTime__ is None:
            return False
        else:
            diffSeconds = (now - self.__lastOrderTime__).seconds + (now - self.__initiatedTime__).microseconds/1000000.0
            return diffSeconds < self.__coldSeconds__ and diffSeconds >= 0