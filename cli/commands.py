class CLI:

    def __init__(self, engine):

        self.engine = engine

    ######################################

    def execute(self, args):

        if args.command == "sync":

            # Route search mode to engine.search(), others to engine.sync()
            if args.mode == "search":

                self.engine.search(
                    args.module,
                    attacker=args.attacker,
                    attacker_name=args.attacker_name,
                    defender=args.defender,
                    defender_name=args.defender_name,
                    chain=args.chain,
                    result=args.result,
                    player=getattr(args, 'player', None),
                    item=getattr(args, 'item', None),
                    category=getattr(args, 'category', None),
                    event_type=getattr(args, 'event_type', None),
                    limit=args.limit,
                    oldest_first=args.oldest,
                )

            else:

                self.engine.sync(
                    args.module,
                    mode=args.mode,
                    filters=args.filters,
                    from_timestamp=args.from_timestamp,
                    to_timestamp=args.to_timestamp,
                    pages=getattr(args, 'pages', 50),
                )

        elif args.command == "report":

            self.engine.report(
                args.module,
                args.report_type,
                chain_id=getattr(args, 'chain_id', None),
                war_id=getattr(args, 'war_id', None),
                hit_number=getattr(args, 'hit_number', None),
                player=getattr(args, 'player', None),
                item=getattr(args, 'item', None),
                category=getattr(args, 'category', None),
                top_n=getattr(args, 'top_n', 10),
                limit=getattr(args, 'limit', 50),
                total_payout=getattr(args, 'total_payout', None),
                xanax_cost=getattr(args, 'xanax_cost', 0),
                faction_cut=getattr(args, 'faction_cut', 0),
                bounty_cost=getattr(args, 'bounty_cost', 0),
                per_assist=getattr(args, 'per_assist', 0),
                pay_outside_hits=getattr(args, 'pay_outside_hits', 0),
                stacking_days=getattr(args, 'stacking_days', 0),
                temp_return_days=getattr(args, 'temp_return_days', 2),
            )

        elif args.command == "crime_rules":

            self.engine.manage_crime_rules(
                action=args.action,
                tier=getattr(args, 'tier', None),
                crime_name=getattr(args, 'crime_name', None),
                position=getattr(args, 'position', None),
                min_cpr=getattr(args, 'min_cpr', None),
            )

        elif args.command == "revive_requests":

            self.engine.manage_revive_requests(
                action=args.action,
                request_id=getattr(args, 'request_id', None),
                requested_at=getattr(args, 'requested_at', None),
                requester_name=getattr(args, 'requester_name', None),
                requester_id=getattr(args, 'requester_id', None),
                target_id=getattr(args, 'target_id', None),
                target_name=getattr(args, 'target_name', None),
                source=getattr(args, 'source', 'external'),
                notes=getattr(args, 'notes', None),
                status=getattr(args, 'status', 'pending'),
                limit=getattr(args, 'limit', 50),
                window_seconds=getattr(args, 'window_seconds', 21600),
            )

        elif args.command == "revive_listener":

            self.engine.manage_revive_listener(
                action=args.action,
                host=getattr(args, 'host', None),
                port=getattr(args, 'port', None),
                poll_seconds=getattr(args, 'poll_seconds', 15),
                window_seconds=getattr(args, 'window_seconds', 21600),
            )

        elif args.command == "discord":

            self.engine.manage_discord(
                action=args.action,
                token=getattr(args, 'token', None),
                prefix=getattr(args, 'prefix', None),
                guild_id=getattr(args, 'guild_id', None),
                timeout_seconds=getattr(args, 'timeout_seconds', None),
            )

        elif args.command == "payout":

            self.engine.payout(
                args.module,
                war_id=args.war_id,
                total_payout=args.total_payout,
                xanax_cost=args.xanax_cost,
                faction_cut=args.faction_cut,
                bounty_cost=args.bounty_cost,
                per_assist=args.per_assist,
                pay_outside_hits=args.pay_outside_hits,
            )

        elif args.command == "payout_csv":

            self.engine.payout_csv(
                args.module,
                war_id=args.war_id,
                csv_path=args.csv_path,
                total_payout=args.total_payout,
                xanax_cost=args.xanax_cost,
                faction_cut=args.faction_cut,
                bounty_cost=args.bounty_cost,
                per_assist=args.per_assist,
                pay_outside_hits=args.pay_outside_hits,
            )

        elif args.command == "watch":

            self.engine.watch(
                args.module,
                cooldown=args.cooldown,
                duration=args.duration,
            )

        elif args.command == "prices":

            self.engine.manage_prices(
                args.action,
                item_id=getattr(args, 'item_id', None),
                price=getattr(args, 'price', None),
                category=getattr(args, 'category', None),
                limit=getattr(args, 'limit', 25),
                min_uses=getattr(args, 'min_uses', 5),
                event_type=getattr(args, 'event_type', 'used'),
                output_path=getattr(args, 'output', 'data/manual_price_overrides.csv'),
            )