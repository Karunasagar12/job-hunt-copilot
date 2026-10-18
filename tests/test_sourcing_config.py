"""Profile-driven sourcing and safe budget allocation."""
import json

import pytest

import db
import paths
import profile as prof
import settings
import source_jobs as sj


def configure(titles=None, locations=None, budget=5):
    p = prof.load_profile()
    p['target_titles'] = ['Product Manager'] if titles is None else titles
    p['target_locations'] = ['Paris, France'] if locations is None else locations
    prof.save_profile(p)
    settings.update({'integrations': {'apify': {'max_charge_usd': budget}}})


def test_profile_targets_are_bounded_and_budget_fits():
    titles = [f'Title {i}' for i in range(10)]
    locations = [f'Location {i}' for i in range(12)]
    configure(titles, locations)
    cfg = sj.load_config()
    assert cfg['actor'] == 'automation-lab~linkedin-jobs-scraper'
    assert cfg['titles'] == titles[:8]
    assert [loc['linkedin_location'] for loc in cfg['locations']] == locations[:8]
    assert all(loc['max_jobs'] == 25 for loc in cfg['locations'])
    assert all(0 < loc['max_charge_usd'] <= 0.02 for loc in cfg['locations'])
    assert sj.worst_case_monthly_usd(cfg) <= cfg['monthly_budget_usd'] == 5
    assert sj.sourcing_ready()


def test_profile_regions_and_remote_prefix():
    configure(locations=['Paris, France', 'Remote Europe', 'Tokyo'])
    locations = sj.load_config()['locations']
    assert [loc['geo'] for loc in locations] == ['eu', 'eu', 'eu']
    assert [loc['remote_only'] for loc in locations] == [False, True, False]


@pytest.mark.parametrize('titles,locations', [([], ['Paris']), (['PM'], [])])
def test_empty_targets_are_not_ready(titles, locations):
    configure(titles, locations)
    assert not sj.sourcing_ready()


def test_missing_profile_is_not_ready():
    paths.profile_path().unlink()
    assert not sj.sourcing_ready()
    assert sj.load_config()['titles'] == []


def test_missing_settings_uses_default_budget():
    configure()
    paths.settings_path().unlink()
    assert sj.load_config()['monthly_budget_usd'] == 5


@pytest.mark.parametrize('budget', [2, 0.0248, 0.024799999999999998, 4.99999, 20])
def test_allocation_never_rounds_above_monthly_budget(budget):
    configure(locations=[f'Location {i}' for i in range(8)], budget=budget)
    cfg = sj.load_config()
    assert cfg['monthly_budget_usd'] == min(budget, 5)
    assert sj.worst_case_monthly_usd(cfg) <= cfg['monthly_budget_usd'] <= 5
    assert sum(loc['max_charge_usd'] for loc in cfg['locations']) * 31 <= cfg['monthly_budget_usd']


@pytest.mark.parametrize('budget', [0, 0.00001, -1, 'invalid', None, float('inf'), float('nan')])
def test_unaffordable_budget_records_skip_without_provider_or_reservation(budget, monkeypatch):
    configure(budget=budget)
    calls = []
    monkeypatch.setattr(sj, 'build_system_prompt', lambda: calls.append('prompt'))
    monkeypatch.setattr(sj.requests, 'post', lambda *args, **kwargs: calls.append('provider'))
    out = sj.run(token='tok', usage=lambda *args: calls.append('usage'))
    assert calls == []
    assert not sj.sourcing_ready()
    assert out['outcome'] == 'skipped'
    latest = db.get_latest_sourcing_run()
    assert latest['outcome'] == 'skipped' and latest['total_usd'] == 0
    assert latest['locations'][0]['status'] == 'skipped'
    assert 'budget' in latest['locations'][0]['error'].lower()


def test_explicit_file_config_still_loads_unchanged(tmp_path):
    legacy = {'actor': 'legacy', 'monthly_budget_usd': 2, 'titles': ['PM'], 'locations': []}
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps(legacy), encoding='utf-8')
    assert sj.load_config(path) == legacy


@pytest.mark.parametrize('budget,cap', [
    (0.00001, 0.02), ('invalid', 0.02), (None, 0.02),
    (float('inf'), 0.02), (float('nan'), 0.02),
    (5, 'invalid'), (5, None), (5, float('inf')), (5, float('nan')),
    (5, 0), (5, -0.01),
])
def test_supplied_invalid_or_unaffordable_config_skips_before_work(budget, cap, monkeypatch):
    cfg = {
        'actor': 'automation-lab~linkedin-jobs-scraper', 'monthly_budget_usd': budget,
        'titles': ['Product Manager'],
        'locations': [dict(linkedin_location='Paris, France', geo='eu', remote_only=False,
                           max_jobs=25, max_charge_usd=cap)],
    }
    calls = []
    monkeypatch.setattr(sj, 'build_system_prompt', lambda: calls.append('prompt'))
    monkeypatch.setattr(sj.requests, 'post', lambda *args, **kwargs: calls.append('provider'))
    out = sj.run(token='tok', config=cfg, usage=lambda *args: calls.append('usage'))
    assert calls == []
    assert not sj.sourcing_ready(cfg)
    assert out['outcome'] == 'skipped'
    latest = db.get_latest_sourcing_run()
    assert latest['outcome'] == 'skipped' and latest['total_usd'] == 0
    assert latest['locations'][0]['status'] == 'skipped'


def test_valid_supplied_caps_keep_legacy_reservation_behavior(monkeypatch):
    cfg = {
        'actor': 'automation-lab~linkedin-jobs-scraper', 'monthly_budget_usd': 0.03,
        'titles': ['Product Manager'],
        'locations': [dict(linkedin_location=name, geo='eu', remote_only=False,
                           max_jobs=25, max_charge_usd=cap)
                      for name, cap in [('Paris', 0.03), ('Berlin', 0.04)]],
    }
    launched = []
    monkeypatch.setattr(sj, 'build_system_prompt', lambda: 'profile')

    def fetch(loc, *args):
        launched.append(loc['linkedin_location'])
        return [], dict(location=loc['linkedin_location'], status='ok', scraped=0, usd=0)

    assert sj.sourcing_ready(cfg)
    out = sj.run(token='tok', config=cfg, usage=lambda token: 0, fetch=fetch)
    assert launched == ['Paris']
    assert out['outcome'] == 'partial'
    assert [loc['status'] for loc in out['locations']] == ['ok', 'budget_exhausted']


@pytest.mark.parametrize('posting_location,job_id,expected_status', [
    ('Paris, Île-de-France, France', '9300009901', 'new'),
    ('Lyon, France', '9300009902', 'filtered'),
])
def test_generated_city_target_matches_provider_location_components(
        monkeypatch, posting_location, job_id, expected_status):
    configure(locations=['Paris, France'])
    cfg = sj.load_config()
    monkeypatch.setattr(sj, 'build_system_prompt', lambda: 'profile')

    def fetch(loc, *args):
        return [{
            'id': job_id, 'title': 'Product Manager', 'companyName': 'Example Labs',
            'location': posting_location,
            'descriptionText': 'Product strategy and delivery requirements. ' * 20,
            'url': f'https://www.linkedin.com/jobs/view/{job_id}/',
        }], dict(location=loc['linkedin_location'], status='ok', scraped=1, usd=0)

    out = sj.run(token='tok', config=cfg, usage=lambda token: 0, fetch=fetch,
                 call=lambda *args, **kwargs: '{"fit_score":77,"reasons":[],"concerns":[]}')
    assert out['outcome'] == 'success'
    assert out['locations'][0]['new'] == int(expected_status == 'new')
    assert out['locations'][0]['filtered'] == int(expected_status == 'filtered')
    row = next(row for row in db.get_sourced_jobs(['new', 'filtered'])
               if row['linkedin_job_id'] == job_id)
    assert row['status'] == expected_status
    assert row['filter_reason'] == (None if expected_status == 'new' else 'location')
    assert row['fit_score'] == (77 if expected_status == 'new' else None)
