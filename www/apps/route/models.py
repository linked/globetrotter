from django.db import models
from django.shortcuts import get_object_or_404
from django.conf import settings
from ordered_model.models import OrderedModel
from apps.models import *
import datetime

RULE_TYPES = (
        ('ip', 'IP'),
        ('referer', 'Referer URL'),
        ('country', 'Country'),
        ('param', 'URL Parameter (e.g. "c1=5")'),
        ('hour', 'Current hour, EST, 24h format'), ('random', 'Random N % of your traffic'),
    )
MATCH_TYPES = (
        ('eq', '= (EQUALS)'),
        ('neq', '!= (NOT EQUALS)'),
        ('regex', '~= (REGEX)'),
        ('nregex', '!~= (NOT REGEX)'),
        ('gt', '> (GREATER THAN)'),
        ('lt', '< (LESS THAN)'),
        ('in', 'in (Any,of,comma,seperated)'),
        ('nin', 'not in (Any,of,comma,seperated)'),
        )


def stub():
    from apps.models import randHash40
    return randHash40()[:6]
class RuleSet(user_owned_model):
    nickname = models.CharField(max_length=128, unique=True)
    short_url_stub = models.CharField(max_length=20, default=stub, unique=True)
    if_all_rules_fail_redirect_to = models.URLField(verify_exists=False, max_length=1024)
    and_pass_subids = models.BooleanField(default=False)
    def __unicode__(self): return self.nickname
    def url_stub_for(self):
        if len(self.short_url_stub):
            return self.short_url_stub
        else: return self.id
    def url(self):
        try:
            return 'http://%s/route/%s'%(settings.HOST_URL, self.url_stub_for())
        except: return '/route/%s'%self.url_stub_for()
    def to_json(self):
        import json
        return json.dumps({
        'id': self.id,
        'user_id': self.user.id,
        'nickname': self.nickname,
        'short_url_stub': self.short_url_stub,
        'if_all_rules_fail_redirect_to': self.if_all_rules_fail_redirect_to, 
        'and_pass_subids': self.and_pass_subids,
        'rules': [r.to_json() for r in self.rule_set.all()] })

    @staticmethod
    def nickname_key(name_or_id):
        return 'RuleSet_%s'%name_or_id

    @staticmethod
    def find_ruleset(name_or_id):
        find = RuleSet.objects.filter(short_url_stub=name_or_id)
        if find.count() > 0:
            return find[0]
        find = RuleSet.objects.filter(pk=name_or_id)
        if find.count() > 0:
            return find[0]
        else: 
            return False

    @staticmethod
    def cached_find_ruleset(name_or_id):
        import json
        from django.core.cache import cache
        key = RuleSet.nickname_key(name_or_id)
        if not cache.get(key):
            rs = RuleSet.find_ruleset(name_or_id)
            if not rs:
                cache.set(key, 'empty', 10)
                return False
            else:
                cache.set(key, rs.to_json(), 10)
        try: return json.loads(cache.get(key))
        except: return False

    @staticmethod
    def evaluate_rules(rules, visitor):
        for rule in rules:
            if Rule.passes(rule, visitor):
                return rule
        return False

    @staticmethod
    def evaluate_visitor(ruleset, visitor):
        rule = RuleSet.evaluate_rules(ruleset['rules'], visitor)
        default = ruleset.get('if_all_rules_fail_redirect_to', 'about:blank')
        RuleSet.increment_clicks(ruleset['id'])
        if not rule:
            if ruleset['and_pass_subids']: 
                return RuleSet.pass_subids(default, visitor)
            else: return default
        else:
            RuleSet.increment_clicks(ruleset['id'], False, rule['id'])
            target = rule.get('redirect_to', default)
            if rule.get('and_pass_subids', False):
                return RuleSet.pass_subids(target, visitor)
            else:
                return target
                        
    @staticmethod
    def pass_subids(url, visitor):
        return url
    
    @staticmethod
    def form_for(req, id=False, *args, **kwargs):
        from forms import RuleSetForm
        from uni_form.helpers import FormHelper, Submit, Reset
        from uni_form.helpers import Layout, Fieldset, Row, HTML
        if not req.method == 'POST': data = None
        else: data = req.POST
        form = RuleSetForm(req.user, data, *args, **kwargs) 
        form.helper = FormHelper()
        if 'instance' in kwargs:
            form.helper.form_action = '/edit_route/%s'%kwargs['instance'].id
        else: form.helper.form_action = '/create_route'
        form.helper.form_method = 'POST'
        form.helper.add_layout(Layout(
            Row('nickname', 'short_url_stub'),
            Row('if_all_rules_fail_redirect_to', 'and_pass_subids')
            ))
        form.helper.add_input(Submit('save', "Save this form"))
        return form


    @staticmethod
    def clicks_key(ruleset_id, day=False, segment_id=0):
        if segment_id > 0: segment = '_%s'%segment_id
        else: segment = ''
        if not day:
            day = datetime.date.today()
        return ('ruleset_%s%s_clicks_%s'%(ruleset_id,segment,day)
                ).replace('-','_')

    @staticmethod
    def clicks_for(ruleset_id, day=False, segment_id=0):
        from django.core.cache import cache
        key = RuleSet.clicks_key(ruleset_id, day, segment_id)
        return int(cache.get(key, 0))

    @staticmethod
    def increment_clicks(ruleset_id, day=False, segment_id=0):
        from django.core.cache import cache
        key = RuleSet.clicks_key(ruleset_id, day, segment_id)
        if not cache.get(key):
            cache.set(key, 0, 60*60*24*7)
        return cache.incr(key, 1)

    def clicks_today(self):
        return RuleSet.clicks_for(self.id)


    
class Rule(OrderedModel):
    key = models.CharField(max_length=32, choices=RULE_TYPES)
    match_type = models.CharField(max_length=32, choices=MATCH_TYPES)
    value = models.CharField(max_length=1024, default="")
    redirect_to = models.URLField(verify_exists=False, max_length=1024)
    and_pass_subids = models.BooleanField(default=True)
    ruleset = models.ForeignKey(RuleSet)
    class Meta:
        ordering = ('ruleset', 'order')

    def to_json(self):
        import json
        return json.dumps({
            'id': self.id,
            'key': self.key,
            'match_type': self.match_type,
            'value': self.value,
            'redirect_to': self.redirect_to,
            'and_pass_subids': self.and_pass_subids,
            'ruleset': self.ruleset_id })

    @staticmethod
    def passes(obj, visitor):
        if obj['key'] == 'country':
            return Rule.check_matching(
                    settings.GEO_DRIVER.country_code_by_addr(visitor['ip']),
                    obj['match_type'],
                    obj['value'].upper()
                    )
        if obj['key'] == 'ip':
            return Rule.check_matching(visitor['ip'],
                    obj['match_type'],
                    obj['value'])
        if obj['key'] == 'referer':
            return Rule.check_matching(visitor['referer'],
                    obj['match_type'],
                    obj['value'])
        if obj['key'] == 'param':
            return Rule.check_matching(visitor['params'],
                    obj['match_type'],
                    obj['value'])
        if obj['key'] == 'hour':
            return Rule.check_matching(datetime.datetime.now().strftime(
                '%H'), obj['match_type'], obj['value'])
        if obj['key'] == 'random':
            import md5
            v= Rule.check_matching(
                    str(int(md5.new(visitor['ip']).hexdigest(),16)%100+1),
                    obj['match_type'], obj['value'])
            return v
        return True
    @staticmethod
    def check_matching(needle, operator, haystack):
        n,o,h = needle, operator, haystack # shorthand
        if o == 'eq': return n == h
        if o == 'neq': return n != h
        if o == 'regex':
            import re
            try: return bool(re.match(h, n))
            except: return False
        if o == 'nregex':
            import re
            try: return not bool(re.match(h, n))
            except: return False
        if o == 'gt':
            try: return int(n) > int(h)
            except: return False
        if o == 'lt':
            try: return int(n) < int(h)
            except: return False
        if o == 'in': return n in map(lambda s:s.strip(), h.split(','))
        if o == 'nin': return not n in map(lambda s:s.strip(), h.split(','))
        return False
