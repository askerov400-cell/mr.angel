import asyncio
import json
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, AsyncMock, MagicMock
from urllib.error import HTTPError
from kaspi import client, handlers

ROW={"id":"opaque","code":"123","totalPrice":200,"status":"APPROVED_BY_BANK"}
def api(row):
    return {"type":"orders","id":row["id"],"attributes":{k:v for k,v in row.items() if k!="id"}}
def update(data="",owner=123,chat="private"):
    message=NS(reply_text=AsyncMock())
    return NS(effective_user=NS(id=owner),effective_chat=NS(id=owner,type=chat),
              message=message,callback_query=NS(data=data,message=message,answer=AsyncMock()))
class ClientTests(unittest.TestCase):
    def test_get_whitelist_and_strip_buyers(self):
        raw=json.dumps({"data":[{**api(ROW),"customer":{"phone":"private"}}]}).encode()
        response=MagicMock()
        response.__enter__.return_value.read.return_value=raw
        opener=MagicMock();opener.open.return_value=response
        with patch.dict("os.environ",{"KASPI_API_TOKEN":" key "}),patch.object(client,"build_opener",return_value=opener):
            result=client.orders("NEW")
        req=opener.open.call_args.args[0]
        self.assertEqual(req.get_method(),"GET")
        self.assertEqual(req.get_header("X-auth-token"),"key")
        self.assertTrue(req.full_url.startswith("https://kaspi.kz/shop/api/v2/orders?"))
        self.assertNotIn("customer",result[0])
        self.assertIn("creationDate",req.full_url)
    def test_redirect_block(self):
        self.assertIsNone(client.NoRedirect().redirect_request(None,None,302,"",{}, "https://evil.invalid"))
    def test_changed_order_never_posts(self):
        for changed in ({**ROW,"status":"COMPLETED"},{**ROW,"totalPrice":300},{**ROW,"id":"other"}):
            with patch.object(client,"detail",return_value=changed),patch.object(client,"request") as req:
                with self.assertRaises(client.KaspiError):client.change(ROW,"accept")
                req.assert_not_called()
    def test_accept_exact_response(self):
        confirmed={**ROW,"status":"ACCEPTED_BY_MERCHANT"}
        with patch.object(client,"detail",return_value=ROW),patch.object(client,"request",return_value=api(confirmed)) as req:
            self.assertEqual(client.change(ROW,"accept")["status"],confirmed["status"])
        self.assertEqual(req.call_args.kwargs["payload"]["data"]["attributes"]["status"],confirmed["status"])
    def test_cancel_reason_and_no_false_success(self):
        with patch.object(client,"detail",return_value=ROW),patch.object(client,"request",return_value=api(ROW)) as req:
            with self.assertRaises(client.KaspiError):client.change(ROW,"cancel","MERCHANT_OUT_OF_STOCK")
        self.assertEqual(req.call_args.kwargs["payload"]["data"]["attributes"]["cancellationReason"],"MERCHANT_OUT_OF_STOCK")
        with self.assertRaises(ValueError):client.change(ROW,"cancel","invented")
    def test_terminal_status_no_post(self):
        terminal={**ROW,"status":"COMPLETED"}
        with patch.object(client,"detail",return_value=terminal),patch.object(client,"request") as req:
            with self.assertRaises(client.KaspiError):client.change(terminal,"cancel","MERCHANT_OUT_OF_STOCK")
            req.assert_not_called()
    def test_failure_does_not_expose_body(self):
        with patch.dict("os.environ",{"KASPI_API_TOKEN":"secret"}),patch.object(client,"build_opener") as build:
            build.return_value.open.side_effect=HTTPError("private",403,"secret",{},None)
            with self.assertRaises(client.KaspiError) as caught:client.request()
        self.assertNotIn("secret",str(caught.exception))
    def test_invalid_query(self):
        with self.assertRaises(ValueError):client.orders("unknown")
        with self.assertRaises(ValueError):client.orders("NEW",-1)
    def test_payload_size(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b"x"*(2*1024*1024+1)
        with patch.dict("os.environ",{"KASPI_API_TOKEN":"key"}),patch.object(client,"build_opener") as build:
            build.return_value.open.return_value=response
            with self.assertRaises(client.KaspiError):client.request()
class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env=patch.dict("os.environ",{"KASPI_OWNER_ID":"123"})
        self.env.start();self.addCleanup(self.env.stop)
    async def test_owner_guard(self):
        with patch.object(handlers,"orders") as fetch:
            await handlers.callback(update("kaspi:list:NEW:0",owner=456),NS(user_data={}))
            await handlers.callback(update("kaspi:list:NEW:0",chat="group"),NS(user_data={}))
            fetch.assert_not_called()
    async def test_list_and_card(self):
        ctx=NS(user_data={});u=update("kaspi:list:NEW:0")
        with patch.object(handlers,"orders",return_value=[ROW]):await handlers.callback(u,ctx)
        self.assertEqual(len(ctx.user_data["kaspi_cards"]),1)
        self.assertIn("123",u.message.reply_text.call_args.args[0])
    async def test_confirmation_no_early_write(self):
        ctx=NS(user_data={});nonce=handlers.put(ctx,ROW)
        with patch.object(handlers,"detail",return_value=ROW),patch.object(handlers,"change") as write:
            await handlers.callback(update("kaspi:accept:"+nonce),ctx)
            write.assert_not_called()
        self.assertEqual(ctx.user_data["kaspi_pending"]["action"],"accept")
    async def test_reason_required(self):
        ctx=NS(user_data={});nonce=handlers.put(ctx,ROW)
        with patch.object(handlers,"detail",return_value=ROW):
            await handlers.callback(update("kaspi:cancel:"+nonce),ctx)
            self.assertNotIn("kaspi_pending",ctx.user_data)
            await handlers.callback(update("kaspi:reason:"+nonce+":2"),ctx)
        self.assertEqual(ctx.user_data["kaspi_pending"]["reason"],"MERCHANT_OUT_OF_STOCK")
    async def test_one_use_even_on_failure(self):
        ctx=NS(user_data={"kaspi_pending":{"nonce":"yes","at":time.monotonic(),"row":ROW,"action":"accept","reason":None}})
        with patch.object(handlers,"change",side_effect=client.KaspiError("unknown")) as write:
            await handlers.callback(update("kaspi:confirm:yes"),ctx)
            await handlers.callback(update("kaspi:confirm:yes"),ctx)
            self.assertEqual(write.call_count,1)
    async def test_expired_nonce(self):
        ctx=NS(user_data={"kaspi_pending":{"nonce":"yes","at":time.monotonic()-601}})
        with patch.object(handlers,"change") as write:
            await handlers.callback(update("kaspi:confirm:yes"),ctx)
            write.assert_not_called()
    async def test_cache_bounded(self):
        ctx=NS(user_data={})
        for _ in range(25):handlers.put(ctx,ROW)
        self.assertEqual(len(ctx.user_data["kaspi_cards"]),20)

class StatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_totals_deduplicated_and_limit_labelled(self):
        from kaspi import statistics
        completed={**ROW,"status":"COMPLETED"}
        with patch.object(statistics,"orders",return_value=[completed]*100):
            report=await statistics.summary()
        self.assertIn("Всего в выборке: 1",report)
        self.assertIn("200.00",report)
        self.assertIn("неполная",report)
        self.assertIn("не прибыль",report)
    async def test_nan_amount_fails_closed(self):
        from kaspi import statistics
        with patch.object(statistics,"orders",return_value=[{**ROW,"status":"COMPLETED","totalPrice":"NaN"}]):
            with self.assertRaises(client.KaspiError):await statistics.summary()
    async def test_api_failure_no_partial_report(self):
        from kaspi import statistics
        with patch.object(statistics,"orders",side_effect=client.KaspiError("unavailable")):
            with self.assertRaises(client.KaspiError):await statistics.summary()

class DiagnosisTests(unittest.TestCase):
    def test_timeout_is_distinct_and_safe(self):
        with patch.dict("os.environ",{"KASPI_API_TOKEN":"key"}),patch.object(client,"build_opener") as build:
            build.return_value.open.side_effect=TimeoutError("private")
            with self.assertRaises(client.KaspiError) as caught:client.request()
        self.assertEqual(caught.exception.code,"timeout")
        self.assertNotIn("private",str(caught.exception))
    def test_invalid_json_is_distinct(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b"<html>private</html>"
        with patch.dict("os.environ",{"KASPI_API_TOKEN":"key"}),patch.object(client,"build_opener") as build:
            build.return_value.open.return_value=response
            with self.assertRaises(client.KaspiError) as caught:client.request()
        self.assertEqual(caught.exception.code,"invalid_json")
        self.assertNotIn("private",str(caught.exception))
    def test_unknown_mutation_not_retried(self):
        with patch.dict("os.environ",{"KASPI_API_TOKEN":"key"}),patch.object(client,"build_opener") as build:
            build.return_value.open.side_effect=TimeoutError("private")
            with self.assertRaises(client.KaspiError) as caught:client.request(payload={"data":{}})
        self.assertEqual(build.return_value.open.call_count,1)
        self.assertEqual(caught.exception.code,"timeout")
