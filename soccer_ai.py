"""
햄스터봇 축구 AI 전략: 공과 로봇 위치로 로봇마다 목표 지점과 역할을 정합니다.

좌표는 카메라 영상의 픽셀 좌표이고, AI 골대는 화면 왼쪽, 상대(Player) 골대는 오른쪽이라고 가정합니다.

  전략 1  두 대 모두 공격   : 공에 가까운 로봇이 공을 몰고, 다른 로봇은 옆에서 따라가며 받쳐줌
  전략 2  공격 1 + 수비 1   : 로봇 1 은 항상 공격, 로봇 2 는 항상 골키퍼
  전략 3  가까우면 몰고 가기 : 공에 가까운 로봇이 몰고 가다가, 공이 멀어지면 수비로 돌아감
"""
import math
from dataclasses import dataclass

STRATEGIES = {
    1: "두 대 모두 공격",
    2: "1대 공격 + 1대 수비",
    3: "가까우면 몰고가기 / 멀면 수비",
}

ROLE_NAMES = {"attack": "공격", "support": "지원", "keeper": "골키퍼", "defend": "수비"}

BEHIND = 60          # 공 뒤 어느 거리에서 밀기 자세를 잡을지 (px)
PUSH_THROUGH = 50    # 정렬되면 공 너머 이 거리까지 밀고 나감
AROUND = 70          # 공 앞에 있을 때 옆으로 비켜 도는 거리
ALIGN_TOL = 25       # 공-골대 직선에서 이 정도 이내면 정렬된 것으로 봄
SWITCH_MARGIN = 40   # 공격수를 바꾸려면 상대가 이만큼 더 가까워야 함 (역할이 자주 바뀌지 않게)
KEEPER_GAP = 150     # 골키퍼가 AI 골대 앞에서 떨어져 서는 거리
MARGIN = 30          # 목표 지점이 화면 가장자리로 나가지 않게 하는 여백


@dataclass
class Field:
    w: int
    h: int
    ai_goal: tuple | None = None   # (x, y, w, h)
    p_goal: tuple | None = None

    def ai_goal_center(self):
        if self.ai_goal:
            x, y, w, h = self.ai_goal
            return x + w / 2, y + h / 2
        return 0.0, self.h / 2

    def p_goal_center(self):
        if self.p_goal:
            x, y, w, h = self.p_goal
            return x + w / 2, y + h / 2
        return float(self.w), self.h / 2

    def p_goal_target(self):
        """공을 밀어 넣을 지점: 골대 입구가 아니라 안쪽 깊숙한 곳(오른쪽 골대의 80% 지점).
        공 '전체'가 골대에 들어가야 득점이므로 입구에서 멈추지 않고 끝까지 밀게 한다."""
        if self.p_goal:
            x, y, w, h = self.p_goal
            return x + w * 0.8, y + h / 2
        return float(self.w), self.h / 2

    def clamp(self, x, y):
        return (int(max(MARGIN, min(self.w - MARGIN, x))),
                int(max(MARGIN, min(self.h - MARGIN, y))))


@dataclass
class Order:
    target: tuple       # (x, y)
    role: str           # attack / support / keeper / defend
    is_attacker: bool   # True: 빠르게, 목표 근처에서도 계속 밀기 / False: 느리게, 도착하면 정지


def _unit(dx, dy):
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def push_target(robot, ball, goal):
    """공을 goal 쪽으로 몰고 가기 위한 다음 목표 지점."""
    bx, by = ball
    ux, uy = _unit(goal[0] - bx, goal[1] - by)        # 공 → 상대 골대 방향
    rx, ry = robot[0] - bx, robot[1] - by
    along = rx * ux + ry * uy                          # +: 로봇이 공보다 골대 쪽에 있음
    lateral = rx * -uy + ry * ux                       # 공-골대 직선에서 옆으로 벗어난 거리
    behind = (bx - ux * BEHIND, by - uy * BEHIND)

    if along > -15:
        # 공 앞에 있으면 그대로 뒤로 가다 공을 우리 골대 쪽으로 차게 되므로 옆으로 돌아간다
        side = 1 if lateral >= 0 else -1
        return behind[0] + -uy * AROUND * side, behind[1] + ux * AROUND * side
    if abs(lateral) < ALIGN_TOL:
        return bx + ux * PUSH_THROUGH, by + uy * PUSH_THROUGH   # 정렬됨 → 밀고 나가기
    return behind


def support_target(ball, goal, attacker):
    """공격수와 반대편 옆, 조금 뒤에서 따라가는 지원 위치."""
    bx, by = ball
    ux, uy = _unit(goal[0] - bx, goal[1] - by)
    side = 1 if (attacker[0] - bx) * -uy + (attacker[1] - by) * ux < 0 else -1
    return bx - ux * 130 + -uy * 90 * side, by - uy * 130 + ux * 90 * side


def keeper_target(field, ball):
    """AI 골대 앞에서 공의 높이를 따라 움직이는 골키퍼 위치."""
    if field.ai_goal:
        x, y, w, h = field.ai_goal
        return x + w + KEEPER_GAP, max(y + 30, min(ball[1], y + h - 30))
    return 200, max(100, min(ball[1], field.h - 100))


def defend_target(field, ball):
    """골키퍼보다 앞, 공과 AI 골대 사이를 막는 수비 위치."""
    gx, gy = field.ai_goal_center()
    kx, _ = keeper_target(field, ball)
    x = gx + (ball[0] - gx) * 0.5
    return max(kx + 60, x), gy + (ball[1] - gy) * 0.5


class Planner:
    """전략에 따라 역할을 나누고 목표를 정한다. 역할이 매 프레임 바뀌지 않도록 상태를 기억한다."""

    def __init__(self):
        self.attacker = None      # 현재 공격을 맡은 로봇 키
        self.chasing = False      # 전략 3: 지금 공을 몰고 가는 중인지

    def _closest(self, robots, ball):
        dist = {k: math.hypot(r[0] - ball[0], r[1] - ball[1]) for k, r in robots.items()}
        best = min(dist, key=dist.get)
        # 지금 공격수보다 확실히 더 가까울 때만 공격수를 바꾼다
        if self.attacker in dist and dist[best] > dist[self.attacker] - SWITCH_MARGIN:
            best = self.attacker
        self.attacker = best
        return best, dist

    def plan(self, strategy, robots, ball, field):
        """robots: {"r1": (x, y, angle), "r2": ...} 화면에 보이는 로봇만. 반환: {키: Order}"""
        if not robots:
            return {}
        goal = field.p_goal_target()

        def attack(k):
            return Order(field.clamp(*push_target(robots[k], ball, goal)), "attack", True)

        def keeper():
            return Order(field.clamp(*keeper_target(field, ball)), "keeper", False)

        if len(robots) == 1:
            (k,) = robots
            return {k: attack(k)}

        if strategy == 1:
            first, _ = self._closest(robots, ball)
            other = next(k for k in robots if k != first)
            sup = support_target(ball, goal, robots[first])
            return {first: attack(first), other: Order(field.clamp(*sup), "support", False)}

        if strategy == 2:
            self.attacker = "r1"
            return {"r1": attack("r1"), "r2": keeper()}

        # 전략 3: 가까운 로봇이 공 근처에 있으면 몰고 가고, 공이 멀어지면 둘 다 수비
        first, dist = self._closest(robots, ball)
        other = next(k for k in robots if k != first)
        enter, leave = field.w * 0.35, field.w * 0.45   # 들어갈 때와 나올 때 기준을 달리해 떨림 방지
        self.chasing = dist[first] < (leave if self.chasing else enter)
        if self.chasing:
            return {first: attack(first), other: keeper()}
        return {first: Order(field.clamp(*defend_target(field, ball)), "defend", False), other: keeper()}
