import json
import unittest
from pathlib import Path

from cointos import coins


class CointelIdentityTests(unittest.TestCase):
    def test_each_identity_owns_credentials_station_and_archive(self):
        profiles = [coins.profile(name) for name in coins.names()]
        self.assertEqual(len(profiles), 3)
        for field in ('identity', 'name', 'station', 'telegram_env'):
            self.assertEqual(len({p[field] for p in profiles}), 3, field)
        self.assertEqual({p['identity'] for p in profiles},
                         {'cointelprofessional', 'cointelamateur', 'cointelpersonal'})
        for name in coins.names():
            self.assertNotEqual(coins.state(coins.profile(name)['identity']), 'coin')

    def test_the_historical_coin_keeps_its_archive(self):
        self.assertEqual(coins.profile(None), {})
        self.assertEqual(coins.state(None), 'coin')

    def test_an_unknown_or_incomplete_identity_is_refused(self):
        with self.assertRaises(ValueError):
            coins.profile('enterprise')
        with self.assertRaises(ValueError):
            coins.profile('broken', base=self._base({'identity': '', 'name': 'x'}))

    def test_unit_names_are_per_identity(self):
        self.assertEqual(coins.unit('personal'), 'cointel-personal-coin.service')
        self.assertEqual(len({coins.unit(n) for n in coins.names()}), 3)

    def test_cli_controls_the_identity_services_instead_of_the_old_poller(self):
        from cointos import cli
        from unittest import mock
        expected = ['cointosd.service', *[coins.unit(n) for n in coins.names()]]
        self.assertEqual(cli.UNITS, expected)
        self.assertNotIn('cointos-coin.service', cli.UNITS)
        with mock.patch.object(cli, 'systemctl') as systemctl:
            cli.up()
        systemctl.assert_called_once_with('start', *expected)

    def test_coin_unit_template_carries_the_identity(self):
        template = Path('systemd/cointos-coin.service').read_text()
        self.assertIn('Environment=COINTEL=@COINTEL@', template)
        self.assertIn('WorkingDirectory=@STATION@', template)

    def _base(self, document):
        import tempfile
        directory = Path(tempfile.mkdtemp())
        (directory / 'broken.json').write_text(json.dumps(document))
        return directory


if __name__ == '__main__':
    unittest.main()
