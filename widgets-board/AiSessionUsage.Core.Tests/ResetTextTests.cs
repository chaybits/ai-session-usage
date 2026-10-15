namespace AiSessionUsage.Core.Tests;

[TestClass]
public sealed class ResetTextTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 11, 12, 0, 0, TimeSpan.Zero);
    private static readonly TimeZoneInfo Utc = TimeZoneInfo.Utc;
    private static readonly TimeZoneInfo Plus3 = TimeZoneInfo.CreateCustomTimeZone("plus3", TimeSpan.FromHours(3), "plus3", "plus3");

    [TestMethod]
    public void Unknown_reset_is_empty()
    {
        Assert.AreEqual("", ResetText.WithClock(null, Now, Utc));
        Assert.AreEqual("", ResetText.Countdown(null, Now));
    }

    [TestMethod]
    public void Passed_and_now()
    {
        Assert.AreEqual("reset", ResetText.WithClock(Now.AddSeconds(-61), Now, Utc));
        Assert.AreEqual("now", ResetText.WithClock(Now.AddSeconds(-60), Now, Utc));
        Assert.AreEqual("now", ResetText.WithClock(Now.AddSeconds(30), Now, Utc));
        Assert.AreEqual("reset", ResetText.Countdown(Now.AddSeconds(-61), Now));
        Assert.AreEqual("now", ResetText.Countdown(Now.AddSeconds(30), Now));
    }

    [TestMethod]
    public void Hours_and_minutes_with_the_clock_time()
    {
        Assert.AreEqual("2h 13m \u00b7 14:13", ResetText.WithClock(Now.AddHours(2).AddMinutes(13), Now, Utc));
        Assert.AreEqual("45m \u00b7 12:45", ResetText.WithClock(Now.AddMinutes(45), Now, Utc));
        Assert.AreEqual("1h 30m \u00b7 13:29", ResetText.WithClock(Now.AddMinutes(89).AddSeconds(36), Now, Utc));
    }

    [TestMethod]
    public void Clock_time_is_in_the_given_zone()
    {
        Assert.AreEqual("2h 13m \u00b7 17:13", ResetText.WithClock(Now.AddHours(2).AddMinutes(13), Now, Plus3));
    }

    [TestMethod]
    public void Countdown_is_the_short_form()
    {
        Assert.AreEqual("45m", ResetText.Countdown(Now.AddMinutes(45), Now));
        Assert.AreEqual("2h 13m", ResetText.Countdown(Now.AddHours(2).AddMinutes(13), Now));
        Assert.AreEqual("3d 4h", ResetText.Countdown(Now.AddDays(3).AddHours(4), Now));
    }

    [TestMethod]
    public void Days_show_the_weekday_until_six_days()
    {
        // 2026-10-11 is a Sunday; three days and four hours later is Wednesday 16:00.
        Assert.AreEqual("3d 4h \u00b7 Wed 16:00", ResetText.WithClock(Now.AddDays(3).AddHours(4), Now, Utc));
        Assert.AreEqual("6d 0h \u00b7 17 Oct", ResetText.WithClock(Now.AddDays(6), Now, Utc));
    }
}
