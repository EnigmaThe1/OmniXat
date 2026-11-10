from test_customer_csv_answers import CustomerCSVAnswerFixture, ANSWER_SCOPES


class CustomerCSVAnswerBrowserTests(CustomerCSVAnswerFixture):
    def open_candidates(self):
        self.prepare()
        page,errors=self.browser(token=self.token(scope=ANSWER_SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect CSV candidates',exact=True).click()
        return page,errors,page.get_by_role('region',name='CSV candidates '+self.evidence,exact=True)

    def test_exact_answer_then_unavailable_after_reload_with_mobile_layout(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_candidates()
        form=panel.get_by_role('form',name='Answer missing_amount')
        form.get_by_label('Exact decimal amount',exact=True).fill('7.500')
        page.get_by_role('button',name='Refresh CSV candidates',exact=True).click()
        expect(form.get_by_label('Exact decimal amount',exact=True)).to_have_value('7.500')
        form.get_by_role('button',name='Save answer',exact=True).click()
        expect(panel).to_contain_text('Recorded answer for missing_amount · row 3, column 2: 7.500')
        expect(panel).to_contain_text('No unanswered cell questions.')
        expect(panel).to_contain_text('amount · row 2, column 2: 12.00')
        page.reload(); page.get_by_role('button',name='Inspect CSV candidates',exact=True).click()
        expect(panel).to_contain_text('7.500')
        self.job=__import__('uuid').uuid4(); self.extract()
        page.get_by_role('button',name='Refresh CSV candidates',exact=True).click()
        form=panel.get_by_role('form',name='Answer missing_amount')
        form.get_by_label('Amount unavailable',exact=True).check()
        expect(form.get_by_label('Exact decimal amount',exact=True)).to_be_disabled()
        form.get_by_role('button',name='Save answer',exact=True).click()
        expect(panel).to_contain_text('Recorded answer for missing_amount · row 3, column 2: unavailable')
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.assertEqual(self.rows('csv_clarification_answers'),2); self.assertEqual(errors,[])

    def test_lost_receipt_retries_exact_job_body_and_actor(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_candidates(); requests=[]
        def lose_once(route):
            request=route.request
            requests.append(request.post_data)
            if len(requests)==1:
                response=self.client.post(self.answer_url,content=request.post_data,
                    headers=self.headers(scope=ANSWER_SCOPES)|{'Content-Type':'application/json','X-OmniXat-Expected-Actor':str(self.user)})
                self.assertEqual(response.status_code,200,response.text)
                route.abort('failed')
            else: route.fallback()
        page.route('**/csv-answers',lose_once)
        form=panel.get_by_role('form',name='Answer missing_amount')
        form.get_by_label('Exact decimal amount',exact=True).fill('8.250')
        form.get_by_role('button',name='Save answer',exact=True).click()
        expect(form.get_by_role('button',name='Retry answer',exact=True)).to_be_enabled()
        expect(form.get_by_label('Exact decimal amount',exact=True)).to_be_disabled()
        other=__import__('uuid').uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-answer-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=ANSWER_SCOPES,sub='fictional-answer-switch')
        form.get_by_role('button',name='Retry answer',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        expect(form.get_by_label('Exact decimal amount',exact=True)).to_be_disabled()
        self.gateway_token=self.token(scope=ANSWER_SCOPES)
        form.get_by_role('button',name='Retry answer',exact=True).click()
        expect(panel).to_contain_text('Recorded answer for missing_amount · row 3, column 2: 8.250')
        self.assertEqual(requests[0],requests[1]); self.assertEqual(requests[0],requests[2]); self.assertEqual(self.rows('csv_clarification_answers'),1)
        self.assertEqual(errors,[])

    def test_permission_loss_clears_candidates_and_denies_pending_answer(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_candidates()
        form=panel.get_by_role('form',name='Answer missing_amount')
        form.get_by_label('Exact decimal amount',exact=True).fill('9.000')
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        form.get_by_role('button',name='Save answer',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        self.assertEqual(panel.text_content(),''); self.assertEqual(self.rows('csv_clarification_answers'),0)
        self.assertEqual(errors,[])

    def test_expired_session_restores_same_pending_answer_after_sign_in_check(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_candidates()
        form=panel.get_by_role('form',name='Answer missing_amount')
        form.get_by_label('Exact decimal amount',exact=True).fill('6.750')
        self.gateway_token=self.token(scope=ANSWER_SCOPES,iat=self.iat-60,exp=self.iat-1)
        form.get_by_role('button',name='Save answer',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        self.assertEqual(panel.text_content(),'')
        expect(page.locator('#reauth')).to_be_visible()
        self.gateway_token=self.token(scope=ANSWER_SCOPES)
        page.locator('#retry').click()
        form=panel.get_by_role('form',name='Answer missing_amount')
        expect(form.get_by_label('Exact decimal amount',exact=True)).to_have_value('6.750')
        expect(form.get_by_label('Exact decimal amount',exact=True)).to_be_disabled()
        form.get_by_role('button',name='Retry answer',exact=True).click()
        expect(panel).to_contain_text('Recorded answer for missing_amount · row 3, column 2: 6.750')
        self.assertEqual(self.rows('csv_clarification_answers'),1); self.assertEqual(errors,[])
