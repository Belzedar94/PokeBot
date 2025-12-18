# frozen_string_literal: true

require "socket"

begin
  require "json"
rescue LoadError
  module MiniJSON
    class ParseError < StandardError; end

    module_function

    def parse(str)
      Parser.new(str).parse
    end

    def dump(obj)
      Generator.generate(obj)
    end

    def _byte(str, idx)
      if str.respond_to?(:getbyte)
        str.getbyte(idx)
      else
        str[idx]
      end
    end

    def _chr(byte)
      return byte.chr(Encoding::ASCII_8BIT) if defined?(Encoding) && byte.respond_to?(:chr)
      byte.chr
    end

    class Parser
      WS = [9, 10, 13, 32].freeze

      def initialize(str)
        @s = str.to_s.dup
        @s.force_encoding(Encoding::ASCII_8BIT) if defined?(Encoding) && @s.respond_to?(:force_encoding)
        @i = 0
      end

      def parse
        skip_ws
        v = parse_value
        skip_ws
        raise ParseError, "trailing characters" if @i < @s.length
        v
      end

      def skip_ws
        while @i < @s.length && WS.include?(MiniJSON._byte(@s, @i))
          @i += 1
        end
      end

      def peek
        return nil if @i >= @s.length
        MiniJSON._byte(@s, @i)
      end

      def take
        b = peek
        @i += 1
        b
      end

      def expect_bytes(lit)
        if @s[@i, lit.length] == lit
          @i += lit.length
        else
          raise ParseError, "expected #{lit}"
        end
      end

      def parse_value
        c = peek
        case c
        when 123 # {
          parse_object
        when 91 # [
          parse_array
        when 34 # "
          parse_string
        when 116 # t
          expect_bytes("true")
          true
        when 102 # f
          expect_bytes("false")
          false
        when 110 # n
          expect_bytes("null")
          nil
        else
          if c == 45 || (c && c >= 48 && c <= 57)
            parse_number
          else
            raise ParseError, "unexpected byte #{c.inspect}"
          end
        end
      end

      def parse_object
        take # {
        skip_ws
        obj = {}
        if peek == 125 # }
          take
          return obj
        end
        loop do
          skip_ws
          k = parse_string
          skip_ws
          raise ParseError, "expected :" unless take == 58
          skip_ws
          obj[k] = parse_value
          skip_ws
          sep = take
          break if sep == 125
          raise ParseError, "expected , or }" unless sep == 44
        end
        obj
      end

      def parse_array
        take # [
        skip_ws
        arr = []
        if peek == 93 # ]
          take
          return arr
        end
        loop do
          skip_ws
          arr << parse_value
          skip_ws
          sep = take
          break if sep == 93
          raise ParseError, "expected , or ]" unless sep == 44
        end
        arr
      end

      def parse_string
        raise ParseError, "expected string" unless take == 34
        out = +""
        while @i < @s.length
          b = take
          if b == 34
            out.force_encoding(Encoding::UTF_8) if defined?(Encoding) && out.respond_to?(:force_encoding)
            return out
          end
          if b == 92
            esc = take
            case esc
            when 34 then out << "\""
            when 92 then out << "\\"
            when 47 then out << "/"
            when 98 then out << "\b"
            when 102 then out << "\f"
            when 110 then out << "\n"
            when 114 then out << "\r"
            when 116 then out << "\t"
            when 117
              out << parse_unicode_escape
            else
              raise ParseError, "bad escape"
            end
          else
            out << MiniJSON._chr(b)
          end
        end
        raise ParseError, "unterminated string"
      end

      def parse_hex4
        h = @s[@i, 4]
        raise ParseError, "bad unicode escape" unless h && h.length == 4
        @i += 4
        Integer(h, 16)
      rescue StandardError
        raise ParseError, "bad unicode escape"
      end

      def parse_unicode_escape
        code = parse_hex4
        if code >= 0xD800 && code <= 0xDBFF
          if peek == 92 && MiniJSON._byte(@s, @i + 1) == 117
            take # \
            take # u
            low = parse_hex4
            if low >= 0xDC00 && low <= 0xDFFF
              code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
            end
          end
        end
        [code].pack("U")
      end

      def parse_number
        rest = @s[@i, @s.length - @i]
        m = /\A-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+\-]?\d+)?/.match(rest)
        raise ParseError, "bad number" unless m
        num = m[0]
        @i += num.length
        if num.include?(".") || num.include?("e") || num.include?("E")
          Float(num)
        else
          Integer(num)
        end
      rescue StandardError
        raise ParseError, "bad number"
      end
    end

    module Generator
      module_function

      def generate(obj)
        case obj
        when NilClass
          "null"
        when TrueClass
          "true"
        when FalseClass
          "false"
        when Numeric
          obj.to_s
        when String
          quote(obj)
        when Array
          "[" + obj.map { |e| generate(e) }.join(",") + "]"
        when Hash
          "{" + obj.map { |k, v| quote(k.to_s) + ":" + generate(v) }.join(",") + "}"
        else
          quote(obj.to_s)
        end
      end

      def quote(str)
        s = str.to_s
        out = +"\""
        if s.respond_to?(:each_char)
          s.each_char do |ch|
            code = ch.respond_to?(:ord) ? ch.ord : ch[0]
            case ch
            when "\""
              out << "\\\""
            when "\\"
              out << "\\\\"
            when "\b"
              out << "\\b"
            when "\f"
              out << "\\f"
            when "\n"
              out << "\\n"
            when "\r"
              out << "\\r"
            when "\t"
              out << "\\t"
            else
              if code && code < 32
                out << sprintf("\\u%04x", code)
              else
                out << ch
              end
            end
          end
        else
          s.each_byte do |b|
            case b
            when 34
              out << "\\\""
            when 92
              out << "\\\\"
            when 8
              out << "\\b"
            when 12
              out << "\\f"
            when 10
              out << "\\n"
            when 13
              out << "\\r"
            when 9
              out << "\\t"
            else
              if b < 32
                out << sprintf("\\u%04x", b)
              else
                out << b.chr
              end
            end
          end
        end
        out << "\""
      end
    end
  end

  unless defined?(JSON)
    module JSON
      class ParserError < StandardError; end

      def self.parse(str)
        MiniJSON.parse(str)
      rescue MiniJSON::ParseError => e
        raise ParserError, e.message
      end

      def self.dump(obj)
        MiniJSON.dump(obj)
      end

      def self.pretty_generate(obj)
        dump(obj)
      end
    end
  end
end

# In-game TCP bridge for external automation.
# - Newline-delimited JSON protocol
# - Non-blocking socket IO (safe for per-frame update hook)
#
# Commands:
#   {"cmd":"ping"}
#   {"cmd":"state"}
#   {"cmd":"events"}
#   {"cmd":"set","key":"debug","value":true}
module AgentBridge
  HOST = (ENV["ANIL_AGENT_HOST"] || "127.0.0.1").freeze
  PORT = Integer(ENV["ANIL_AGENT_PORT"] || "53135")
  STATUS_PATH = File.join(__dir__, "agent_bridge_status.json").freeze

  MAX_LINES_PER_FRAME = 50
  MAX_BYTES_PER_FRAME = 64 * 1024
  POLL_EVERY_N_FRAMES = 2
  MAX_EVENT_QUEUE = 200

  @server = nil
  @clients = {} # sock => {in:String,out:String}
  @events = []
  @debug = false
  @disabled = false

  @frame = 0
  @last_badges_count = nil
  @last_party_uids = nil
  @last_party_hp = nil
  @uid_cache = {} # object_id => uid

  class << self
    def write_status(kind, extra = {})
      payload = {
        "t" => now_f,
        "kind" => kind.to_s,
        "host" => HOST,
        "port" => PORT,
        "disabled" => !!@disabled
      }
      if extra.is_a?(Hash)
        extra.each { |k, v| payload[k.to_s] = v }
      end
      File.open(STATUS_PATH, "wb") { |f| f.write(json_pretty(payload)) }
    rescue StandardError => e
      begin
        File.open(File.join(__dir__, "agent_bridge_status.txt"), "ab") do |f|
          f.write("write_status failed: #{e.class}: #{e.message}\n")
        end
      rescue StandardError
        # ignore
      end
    end

    def json_parse(str)
      if defined?(::JSON) && ::JSON.respond_to?(:parse)
        ::JSON.parse(str)
      else
        MiniJSON.parse(str)
      end
    end

    def json_dump(obj)
      if defined?(::JSON) && ::JSON.respond_to?(:dump)
        ::JSON.dump(obj)
      elsif defined?(::JSON) && ::JSON.respond_to?(:generate)
        ::JSON.generate(obj)
      else
        MiniJSON.dump(obj)
      end
    end

    def json_pretty(obj)
      if defined?(::JSON) && ::JSON.respond_to?(:pretty_generate)
        ::JSON.pretty_generate(obj)
      else
        json_dump(obj)
      end
    end

    def log(msg)
      return unless @debug
      MKXP.puts("[AgentBridge] #{msg}")
    rescue StandardError
      # ignore
    end

    def now_f
      Time.now.to_f
    rescue StandardError
      0.0
    end

    def push_event(ev)
      @events << ev
      @events.shift while @events.length > MAX_EVENT_QUEUE
    rescue StandardError
      # ignore
    end

    def push_pokemon_acquired(pkmn)
      return if pkmn.nil?
      ev = {
        "type" => "pokemon_acquired",
        "uid" => stable_uid_for(pkmn),
        "species" => safe_to_s(pkmn, :species),
        "name" => safe_to_s(pkmn, :name),
        "level" => safe_int(pkmn, :level),
        "t" => now_f,
        "map_id" => safe_map_id
      }
      push_event(ev)
    rescue StandardError
      # ignore
    end

    def push_badge_earned(badge_id = nil)
      badges = safe_badges_count
      return if badges.nil?
      push_event(
        {
          "type" => "badge_earned",
          "badge_count" => badges,
          "badge_id" => badge_id,
          "t" => now_f,
          "map_id" => safe_map_id
        }
      )
    rescue StandardError
      # ignore
    end

    def start
      return if @disabled
      return if @server

      @server = TCPServer.new(HOST, PORT)
      @server.setsockopt(Socket::SOL_SOCKET, Socket::SO_REUSEADDR, true) if @server.respond_to?(:setsockopt)
      write_status("listening", { "pid" => Process.pid }) rescue nil
      log("listening on #{HOST}:#{PORT}")
    rescue StandardError => e
      @disabled = true
      write_status("start_failed", { "error" => "#{e.class}: #{e.message}" }) rescue nil
      log("failed to start server: #{e.class}: #{e.message}")
    end

    def stop
      @clients.each_key { |sock| safe_close(sock) }
      @clients.clear
      safe_close(@server)
      @server = nil
    end

    def safe_close(io)
      return if io.nil?
      io.close unless io.closed?
    rescue StandardError
      # ignore
    end

    def update
      start
      return if @disabled

      @frame += 1
      poll_state_and_events if (@frame % POLL_EVERY_N_FRAMES).zero?

      accept_clients
      service_clients
    rescue StandardError => e
      log("update error: #{e.class}: #{e.message}")
    end

    def accept_clients
      return unless @server

      loop do
        sock = @server.accept_nonblock
        sock.setsockopt(Socket::IPPROTO_TCP, Socket::TCP_NODELAY, 1) rescue nil
        @clients[sock] = { in: +"", out: +"" }
        log("client connected")
      end
    rescue IO::WaitReadable, Errno::EINTR
      # no pending connections
    rescue StandardError => e
      log("accept error: #{e.class}: #{e.message}")
    end

    def service_clients
      return if @clients.empty?

      bytes_budget = MAX_BYTES_PER_FRAME
      lines_budget = MAX_LINES_PER_FRAME

      @clients.keys.each do |sock|
        st = @clients[sock]
        bytes_budget = read_from_client(sock, st, bytes_budget)
        lines_budget = process_lines(sock, st, lines_budget)
        write_to_client(sock, st)
      rescue StandardError => e
        log("client error: #{e.class}: #{e.message}")
        disconnect(sock)
      end
    end

    def disconnect(sock)
      safe_close(sock)
      @clients.delete(sock)
      log("client disconnected")
    rescue StandardError
      # ignore
    end

    def read_from_client(sock, st, bytes_budget)
      return bytes_budget if bytes_budget <= 0

      data = sock.recv_nonblock([bytes_budget, 4096].min)
      if data.nil? || data.empty?
        disconnect(sock)
        return bytes_budget
      end

      st[:in] << data
      bytes_budget - data.bytesize
    rescue IO::WaitReadable, Errno::EINTR
      bytes_budget
    rescue EOFError, Errno::ECONNRESET, Errno::EPIPE
      disconnect(sock)
      bytes_budget
    end

    def process_lines(sock, st, lines_budget)
      while lines_budget > 0
        nl = st[:in].index("\n")
        break unless nl

        raw = st[:in].slice!(0, nl + 1)
        line = raw.strip
        next if line.empty?

        resp = handle_command(line)
        st[:out] << json_dump(resp) << "\n"
        lines_budget -= 1
      end
      lines_budget
    rescue StandardError => e
      st[:out] << json_dump({ ok: false, error: "#{e.class}: #{e.message}" }) << "\n"
      lines_budget - 1
    end

    def write_to_client(sock, st)
      return if st[:out].empty?

      written = sock.write_nonblock(st[:out])
      st[:out].slice!(0, written) if written && written > 0
    rescue IO::WaitWritable, Errno::EINTR
      # try next frame
    rescue EOFError, Errno::ECONNRESET, Errno::EPIPE
      disconnect(sock)
    end

    def handle_command(line)
      begin
        obj = json_parse(line)
      rescue StandardError
        return { ok: false, error: "invalid json" }
      end
      cmd = obj["cmd"]

      case cmd
      when "ping"
        { ok: true, pong: true }
      when "state"
        { ok: true, state: snapshot_state }
      when "events"
        ev = @events
        @events = []
        { ok: true, events: ev }
      when "set"
        if obj["key"] == "debug"
          @debug = !!obj["value"]
          { ok: true, debug: @debug }
        else
          { ok: false, error: "unknown key" }
        end
      else
        { ok: false, error: "unknown cmd" }
      end
    rescue StandardError => e
      { ok: false, error: "#{e.class}: #{e.message}" }
    end

    def snapshot_state
      {
        "t" => now_f,
        "scene" => current_scene_name,
        "map_id" => safe_map_id,
        "player_xy" => safe_player_xy,
        "player_dir" => safe_player_dir,
        "badges_count" => safe_badges_count,
        "money" => safe_money,
        "party" => safe_party_array,
        "in_battle" => safe_in_battle,
        "message_text" => safe_message_text
      }
    rescue StandardError
      { "t" => now_f }
    end

    def poll_state_and_events
      t = now_f
      map_id = safe_map_id
      badges = safe_badges_count
      party = safe_party_array

      if !@last_badges_count.nil? && !badges.nil? && badges > @last_badges_count
        push_event({ "type" => "badge_earned", "badge_count" => badges, "t" => t, "map_id" => map_id })
      end
      @last_badges_count = badges unless badges.nil?

      uids = party.map { |p| p["uid"] }.compact.uniq
      uid_set = uids.each_with_object({}) { |u, h| h[u] = true }

      if @last_party_uids
        (uid_set.keys - @last_party_uids.keys).each do |new_uid|
          p = party.find { |pp| pp["uid"] == new_uid }
          next unless p
          push_event(
            {
            "type" => "pokemon_acquired",
            "uid" => p["uid"],
            "species" => p["species"],
            "name" => p["name"],
            "level" => p["level"],
            "t" => t,
            "map_id" => map_id
            }
          )
        end
      end
      @last_party_uids = uid_set

      hp_map = {}
      party.each do |p|
        uid = p["uid"]
        hp = p["hp"]
        next if uid.nil? || hp.nil?
        hp_map[uid] = hp

        if @last_party_hp && @last_party_hp.key?(uid)
          last_hp = @last_party_hp[uid]
          if last_hp && last_hp > 0 && hp == 0
            push_event(
              {
              "type" => "pokemon_death",
              "uid" => uid,
              "species" => p["species"],
              "name" => p["name"],
              "level" => p["level"],
              "t" => t,
              "map_id" => map_id
              }
            )
          end
        end
      end
      @last_party_hp = hp_map
    rescue StandardError => e
      log("poll error: #{e.class}: #{e.message}")
    end

    # ---- game state helpers (best-effort) ----

    def current_scene_name
      if defined?(SceneManager) && SceneManager.respond_to?(:scene) && (sc = SceneManager.scene)
        return sc.class.name
      end
      if defined?($scene) && $scene
        return $scene.class.name
      end
      nil
    rescue StandardError
      nil
    end

    def safe_map_id
      return nil unless defined?($game_map) && $game_map
      return $game_map.map_id if $game_map.respond_to?(:map_id)
      nil
    rescue StandardError
      nil
    end

    def safe_player_xy
      return nil unless defined?($game_player) && $game_player
      return [$game_player.x, $game_player.y] if $game_player.respond_to?(:x) && $game_player.respond_to?(:y)
      nil
    rescue StandardError
      nil
    end

    def safe_player_dir
      return nil unless defined?($game_player) && $game_player
      return $game_player.direction if $game_player.respond_to?(:direction)
      nil
    rescue StandardError
      nil
    end

    def player_obj
      return $Trainer if defined?($Trainer) && $Trainer
      return $player if defined?($player) && $player
      nil
    rescue StandardError
      nil
    end

    def safe_badges_count
      p = player_obj
      if p
        if p.respond_to?(:badges)
          b = p.badges
          return b.count { |x| x } if b.is_a?(Array)
        end
        return p.badge_count if p.respond_to?(:badge_count)
        return p.num_badges if p.respond_to?(:num_badges)
      end
      if defined?(pbGetBadgeCount)
        return pbGetBadgeCount
      end
      nil
    rescue StandardError
      nil
    end

    def safe_money
      p = player_obj
      return p.money if p && p.respond_to?(:money)
      nil
    rescue StandardError
      nil
    end

    def stable_uid_for(pkmn)
      return nil if pkmn.nil?
      return pkmn.personalID if pkmn.respond_to?(:personalID)
      oid = pkmn.object_id
      @uid_cache[oid] ||= ((oid ^ (now_f * 1000).to_i) & 0x7fffffff)
    rescue StandardError
      nil
    end

    def safe_party_array
      p = player_obj
      return [] unless p && p.respond_to?(:party)
      party = p.party
      return [] unless party.is_a?(Array)

      party.map do |p|
        {
          "uid" => stable_uid_for(p),
          "species" => safe_to_s(p, :species),
          "name" => safe_to_s(p, :name),
          "level" => safe_int(p, :level),
          "hp" => safe_int(p, :hp),
          "totalhp" => safe_total_hp(p),
          "status" => safe_to_s(p, :status)
        }
      end
    rescue StandardError
      []
    end

    def safe_total_hp(p)
      return safe_int(p, :totalhp) if p.respond_to?(:totalhp)
      return safe_int(p, :totalHP) if p.respond_to?(:totalHP)
      nil
    rescue StandardError
      nil
    end

    def safe_in_battle
      if defined?($game_temp) && $game_temp && $game_temp.respond_to?(:in_battle)
        return !!$game_temp.in_battle
      end
      sc = current_scene_name
      return true if sc && sc.include?("Battle")
      false
    rescue StandardError
      false
    end

    def safe_message_text
      return nil unless defined?($game_message) && $game_message
      if $game_message.respond_to?(:texts)
        texts = $game_message.texts
        return texts.join("\n") if texts.is_a?(Array) && !texts.empty?
      end
      if $game_message.instance_variable_defined?(:@texts)
        texts = $game_message.instance_variable_get(:@texts)
        return texts.join("\n") if texts.is_a?(Array) && !texts.empty?
      end
      nil
    rescue StandardError
      nil
    end

    def safe_int(obj, method_name)
      return nil unless obj.respond_to?(method_name)
      v = obj.public_send(method_name)
      Integer(v) if !v.nil?
    rescue StandardError
      nil
    end

    def safe_to_s(obj, method_name)
      return nil unless obj.respond_to?(method_name)
      v = obj.public_send(method_name)
      return nil if v.nil?
      v.to_s
    rescue StandardError
      nil
    end
  end
end

# ---- Optional hook-based detection (best-effort) ----
begin
  module AgentBridgeHooks
    @installed = false

    def self.install
      return if @installed
      @installed = true

      install_store_hook
      install_badge_hook
    rescue StandardError
      # ignore
    end

    def self.install_store_hook
      # Top-level methods are private instance methods on Object.
      return unless Object.private_method_defined?(:pbStorePokemon) || Object.method_defined?(:pbStorePokemon)

      Object.class_eval do
        next if private_method_defined?(:__agent_bridge_pbStorePokemon) || method_defined?(:__agent_bridge_pbStorePokemon)

        alias __agent_bridge_pbStorePokemon pbStorePokemon
        def pbStorePokemon(*args, &block)
          result = __agent_bridge_pbStorePokemon(*args, &block)
          AgentBridge.push_pokemon_acquired(args[0]) rescue nil
          result
        rescue StandardError
          __agent_bridge_pbStorePokemon(*args, &block)
        end
      end
    rescue StandardError
      # ignore
    end

    def self.install_badge_hook
      method_names = %i[pbReceiveBadge pbGainBadge pbSetBadge pbAddBadge].freeze
      method_names.each do |m|
        next unless Object.private_method_defined?(m) || Object.method_defined?(m)

        alias_sym = "__agent_bridge_#{m}".to_sym
        mn = m
        as = alias_sym

        Object.class_eval do
          next if private_method_defined?(as) || method_defined?(as)

          alias_method as, mn
          define_method(mn) do |*args, &block|
            result = send(as, *args, &block)
            begin
              if mn == :pbSetBadge && args.length >= 2 && !args[1]
                # ignore unsetting
              else
                AgentBridge.push_badge_earned(args[0]) rescue nil
              end
            rescue StandardError
              # ignore
            end
            result
          rescue StandardError
            send(as, *args, &block)
          end
        end
      end
    rescue StandardError
      # ignore
    end
  end

  AgentBridgeHooks.install
rescue StandardError
  # ignore
end

# ---- Update loop hook (must run every frame) ----
begin
  if defined?(Graphics) && Graphics.respond_to?(:update)
    class << Graphics
      unless method_defined?(:__agent_bridge_original_update)
        alias __agent_bridge_original_update update
        def update(*args)
          AgentBridge.update
          __agent_bridge_original_update(*args)
        rescue StandardError
          __agent_bridge_original_update(*args)
        end
      end
    end
  elsif defined?(SceneManager) && SceneManager.respond_to?(:update)
    class << SceneManager
      unless method_defined?(:__agent_bridge_original_update)
        alias __agent_bridge_original_update update
        def update(*args)
          AgentBridge.update
          __agent_bridge_original_update(*args)
        rescue StandardError
          __agent_bridge_original_update(*args)
  end
end

begin
  AgentBridge.write_status("loaded")
rescue StandardError
  # ignore
end

begin
  AgentBridge.start
rescue StandardError
  # ignore
end
    end
  end
rescue StandardError
  # ignore
end

# ---- Fallback pump thread ----
# Some builds load `preload.rb` before `Graphics`/`SceneManager` exist, so the hook
# above may never install. This lightweight background pump keeps the TCP bridge
# responsive regardless of load order.
begin
  unless defined?($ANIL_AGENT_BRIDGE_PUMP_STARTED) && $ANIL_AGENT_BRIDGE_PUMP_STARTED
    $ANIL_AGENT_BRIDGE_PUMP_STARTED = true
    Thread.new do
      loop do
        begin
          AgentBridge.update
        rescue StandardError
          # ignore
        end
        sleep 0.05
      end
    end
  end
rescue StandardError
  # ignore
end
